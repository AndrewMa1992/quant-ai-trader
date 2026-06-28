"""scripts/auto_retrain.py – 每周六自动训练全部5个模型，带验证和自动重试。

Usage: python scripts/auto_retrain.py [--dry-run]
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
from loguru import logger

# ── Paths ──
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from configs.settings import settings

DATA_DIR = BASE / "data"
MODEL_DIR = BASE / "data" / "models"
CACHE_DIR = BASE / "cache"
REPORT_PATH = CACHE_DIR / "weekly_training_report.json"
PID_PATH = BASE / "logs" / "pipeline.pid"

CACHE_DIR.mkdir(exist_ok=True)
MODEL_DIR.mkdir(exist_ok=True)

device = settings.TRAIN_DEVICE

# ── Training configs (2 tiers: default + conservative fallback) ──
TRAIN_CONFIGS: dict[str, dict] = {
    "gbdt": {
        "default": {"epochs": 200, "lr": 0.05, "early_stopping_rounds": 20},
        "fallback": {"epochs": 100, "lr": 0.01, "early_stopping_rounds": 40},
    },
    "transformer": {
        "default": {"epochs": 30, "lr": 1e-4, "batch_size": 32},
        "fallback": {"epochs": 20, "lr": 5e-5, "batch_size": 16},
    },
    "tcn": {
        "default": {"epochs": 50, "lr": 1e-3, "batch_size": 32},
        "fallback": {"epochs": 30, "lr": 5e-4, "batch_size": 16},
    },
    "tft": {
        "default": {"epochs": 30, "lr": 1e-3, "batch_size": 32},
        "fallback": {"epochs": 20, "lr": 5e-4, "batch_size": 16},
    },
    "rl": {
        "default": {"n_steps": 2048, "total_timesteps": 200_000, "lr": 3e-4},
        "fallback": {"n_steps": 1024, "total_timesteps": 100_000, "lr": 1e-4},
    },
}

# Quality thresholds
QUALITY_CHECK: dict[str, dict] = {
    "gbdt": {"max_val_rmse": 0.5},
    "transformer": {"max_val_loss": 1.0},
    "tcn": {"max_val_loss": 0.5},
    "tft": {"max_val_loss": 0.3},
    "rl": {"min_mean_reward": 0},
}

MODEL_FILES: dict[str, str] = {
    "gbdt": "gbdt_v2.joblib",
    "transformer": "transformer_v2.pt",
    "tcn": "tcn_v2.pt",
    "tft": "tft_v2.pt",
    "rl": "rl_v2.joblib",
}


def _load_data() -> tuple[pd.DataFrame, pd.Series]:
    """Load and prepare training data from latest parquet files."""
    from services.model_train_service.data_loader import create_dataset

    tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA"]
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

    df = create_dataset(tickers, start_date=start_date, end_date=end_date)
    if df is None or len(df) < 200:
        # Fallback to raw parquet
        logger.warning("DataLoader returned sparse data, loading raw parquet...")
        parquet_files = sorted(DATA_DIR.glob("*.parquet"))
        if not parquet_files:
            raise RuntimeError("No parquet data found")
        dfs = [pd.read_parquet(pf) for pf in parquet_files[-5:]]
        df = pd.concat(dfs, ignore_index=True)
        df = df.select_dtypes(include=[np.number])
        df = df.dropna(axis=0, thresh=int(df.shape[1] * 0.5)).fillna(0)

    logger.info(f"Training data: {len(df)} rows x {df.shape[1]} cols")

    target_col = "target" if "target" in df.columns else df.columns[-1]
    X = df.drop(columns=[target_col])
    y = df[target_col]

    # Remove near-constant columns
    with np.errstate(invalid="ignore"):
        variance = X.var()
        keep = variance[variance > 1e-10].index
    X = X[keep]
    logger.info(f"After feature filtering: {len(X.columns)} features")

    return X, y


def _train_gbdt(X: pd.DataFrame, y: pd.Series, cfg: dict, save_path: str) -> dict:
    """Train LightGBM model."""
    from services.model_train_service.trainers.gbdt_trainer import GBDTTrainer

    trainer = GBDTTrainer()
    import numpy as np
    X_np = np.nan_to_num(X.values.astype(np.float64), nan=0.0, posinf=0.0, neginf=0.0)
    y_np = np.nan_to_num(y.values.astype(np.float64), nan=0.0, posinf=0.0, neginf=0.0)
    metrics = trainer.fit(pd.DataFrame(X_np, columns=X.columns), pd.Series(y_np),
                          epochs=cfg["epochs"], lr=cfg["lr"],
                          early_stopping_rounds=cfg["early_stopping_rounds"])
    if metrics.get("val_rmse", 999) < QUALITY_CHECK["gbdt"]["max_val_rmse"]:
        trainer.save(save_path)
    return metrics


def _train_dl(model_type: str, trainer_cls, X: pd.DataFrame, y: pd.Series,
              cfg: dict, model_path: str, seq_len: int = 64) -> dict:
    """Generic DL trainer (TCN / Transformer / TFT)."""
    trainer = trainer_cls(seq_len=min(seq_len, len(X) - 10), device=device)

    # NaN safeguard
    X_arr = np.nan_to_num(X.values.astype(np.float32), nan=0.0, posinf=1.0, neginf=-1.0)
    y_arr = np.nan_to_num(y.values.astype(np.float32), nan=0.0, posinf=1.0, neginf=-1.0)

    metrics = trainer.fit(
        pd.DataFrame(X_arr, columns=X.columns), pd.Series(y_arr),
        epochs=cfg.get("epochs", 20), batch_size=cfg.get("batch_size", 32),
        lr=cfg.get("lr", 1e-3),
    )

    val_loss = metrics.get("val_loss", float("inf"))
    max_val_loss = QUALITY_CHECK[model_type].get("max_val_loss", 1.0)
    if val_loss < max_val_loss and not np.isnan(val_loss) and not np.isinf(val_loss):
        trainer.save(model_path)

    return metrics


def _train_rl(X: pd.DataFrame, y: pd.Series, cfg: dict, save_path: str) -> dict:
    """Train RL PPO agent."""
    from services.model_train_service.trainers.rl_trainer import RLTrainer

    trainer = RLTrainer(device=device)
    X_np = X.values.astype(np.float32)
    y_np = y.values.astype(np.float32)
    metrics = trainer.fit(
        pd.DataFrame(X_np, columns=X.columns), pd.Series(y_np),
        n_steps=cfg["n_steps"], total_timesteps=cfg["total_timesteps"],
        lr=cfg.get("lr", 3e-4),
    )
    if metrics.get("mean_reward", -999) > QUALITY_CHECK["rl"]["min_mean_reward"]:
        trainer.save(save_path)
    return metrics


def _restart_pipeline() -> None:
    """Restart the trading pipeline to load new models."""
    import signal as sig_module

    # Find pipeline PID
    if PID_PATH.exists():
        pid = int(PID_PATH.read_text().strip())
        try:
            os.kill(pid, sig_module.SIGTERM)
            logger.info(f"Sent SIGTERM to pipeline PID={pid}")
            time.sleep(3)
        except (ProcessLookupError, ValueError):
            pass

    # Restart via daemon_forever.bat
    bat_path = BASE / "daemon_forever.bat"
    if bat_path.exists():
        subprocess.Popen(
            ["cmd", "/c", str(bat_path)],
            cwd=str(BASE),
            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0,
        )
        logger.info("Pipeline restart triggered")
    else:
        logger.warning(f"daemon_forever.bat not found at {bat_path}")


def main() -> dict[str, Any]:
    """Run the full weekly retrain pipeline. Returns report dict."""
    logger.info(f"{'='*60}")
    logger.info(f"Weekly Auto-Retrain — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    logger.info(f"Device: {device} | GPU: {torch.cuda.get_device_name(0) if device=='cuda' else 'CPU'}")
    logger.info(f"{'='*60}")

    report: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "device": device,
        "models": {},
        "summary": {},
    }

    try:
        X, y = _load_data()
        report["data"] = {"rows": len(X), "features": len(X.columns)}

        # ── Train each model ──
        model_trainers = {
            "gbdt": (None, _train_gbdt),   # GBDT is special
            "transformer": ("services.model_train_service.trainers.transformer_trainer", "TransformerTrainer"),
            "tcn": ("services.model_train_service.trainers.tcn_trainer", "TCNTrainer"),
            "tft": ("services.model_train_service.trainers.tft_trainer", "TFTTrainer"),
            "rl": (None, _train_rl),
        }

        for model_name, (module_path, train_fn) in model_trainers.items():
            logger.info(f"\n--- Training {model_name.upper()} ---")
            save_path = str(MODEL_DIR / MODEL_FILES[model_name])

            # Try default config first
            cfg = TRAIN_CONFIGS[model_name]["default"]
            try:
                if model_name == "gbdt":
                    metrics = _train_gbdt(X, y, cfg, save_path)
                elif model_name == "rl":
                    metrics = _train_rl(X, y, cfg, save_path)
                else:
                    mod = __import__(module_path, fromlist=[model_trainers[model_name][1]])
                    trainer_cls = getattr(mod, model_trainers[model_name][1])
                    metrics = _train_dl(model_name, trainer_cls, X, y, cfg, save_path)

                valid = _check_quality(model_name, metrics)
                report["models"][model_name] = {"tier": "default", "metrics": metrics, "valid": valid}

                if not valid:
                    logger.warning(f"{model_name} default config FAILED, retrying with fallback...")
                    cfg = TRAIN_CONFIGS[model_name]["fallback"]
                    if model_name == "gbdt":
                        metrics = _train_gbdt(X, y, cfg, save_path)
                    elif model_name == "rl":
                        metrics = _train_rl(X, y, cfg, save_path)
                    else:
                        metrics = _train_dl(model_name, trainer_cls, X, y, cfg, save_path)
                    valid = _check_quality(model_name, metrics)
                    report["models"][model_name] = {"tier": "fallback", "metrics": metrics, "valid": valid}

                status = "✅" if valid else "❌"
                logger.info(f"{status} {model_name}: {metrics}")

            except Exception as e:
                logger.error(f"❌ {model_name} error: {e}", exc_info=True)
                report["models"][model_name] = {"tier": "error", "error": str(e), "valid": False}

        # ── Summary ──
        total = len(report["models"])
        passed = sum(1 for m in report["models"].values() if m.get("valid"))
        report["summary"] = {"total_models": total, "passed": passed, "failed": total - passed}

        logger.info(f"\n{'='*60}")
        logger.info(f"RESULTS: {passed}/{total} models passed")
        logger.info(f"{'='*60}")

        # Save report
        REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False))

        # Restart pipeline if at least 3/5 models passed
        if passed >= 3:
            _restart_pipeline()
        else:
            logger.warning("Too many failures, NOT restarting pipeline")

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        report["error"] = str(e)

    return report


def _check_quality(model_name: str, metrics: dict) -> bool:
    """Check if training metrics pass quality thresholds."""
    qc = QUALITY_CHECK[model_name]
    if model_name == "gbdt":
        val_rmse = metrics.get("val_rmse", float("inf"))
        return not np.isnan(val_rmse) and not np.isinf(val_rmse) and val_rmse < qc["max_val_rmse"]
    elif model_name == "rl":
        return metrics.get("mean_reward", -999) > qc["min_mean_reward"]
    else:
        val_loss = metrics.get("val_loss", float("inf"))
        return not np.isnan(val_loss) and not np.isinf(val_loss) and val_loss < qc["max_val_loss"]


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        logger.info("DRY RUN — will not train or restart")
        logger.info(f"Device: {device}, GPU: {torch.cuda.get_device_name(0) if device=='cuda' else 'N/A'}")
    else:
        main()
