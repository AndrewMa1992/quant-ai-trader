"""scripts/run_paper_train.py – Paper/sim mode training pipeline.

Downloads OHLCV → builds dataset → trains GBDT (+ optional DL/RL) → saves to data/models/.

Usage:
  python scripts/run_paper_train.py
  python scripts/run_paper_train.py --models gbdt,transformer --tickers AAPL,MSFT,NVDA
  python scripts/run_paper_train.py --quick   # tiny smoke train
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

# Force paper/sim before importing settings-dependent modules
os.environ.setdefault("QAT_EXECUTION_MODE", "paper")
os.environ.setdefault("QAT_TRADING_SIMULATION_MODE", "true")
os.environ.setdefault("QAT_TRAIN_DEVICE", os.environ.get("QAT_TRAIN_DEVICE", "cpu"))

from configs.settings import settings
from shared.execution_mode import get_execution_mode, is_simulation_mode

MODEL_DIR = BASE / "data" / "models"
DATA_DAILY = BASE / "data" / "daily"
REPORT_PATH = BASE / "cache" / "paper_train_report.json"

DEFAULT_TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD"]


def _resolve_device(requested: str) -> str:
    try:
        import torch

        if requested == "cuda" and torch.cuda.is_available():
            return "cuda"
        if requested == "mps" and getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def download_ohlcv(tickers: list[str], years: int = 2) -> int:
    """Download yfinance daily bars into data/daily/."""
    import yfinance as yf

    DATA_DAILY.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    for ticker in tickers:
        path = DATA_DAILY / f"{ticker}.parquet"
        if path.exists() and path.stat().st_size > 1000:
            continue
        try:
            df = yf.download(ticker, period=f"{years}y", interval="1d", progress=False, auto_adjust=True)
            if df is None or df.empty or len(df) < 100:
                logger.warning(f"Skip {ticker}: insufficient download")
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [str(c[0]).lower() for c in df.columns]
            else:
                df.columns = [str(c).lower() for c in df.columns]
            df.to_parquet(path)
            downloaded += 1
            logger.info(f"  saved {ticker}: {len(df)} bars → {path}")
        except Exception as exc:
            logger.warning(f"  download failed {ticker}: {exc}")
        time.sleep(0.3)
    return downloaded


def build_dataset(tickers: list[str], years: int = 2) -> tuple[pd.DataFrame, pd.Series]:
    """Build X/y from local parquet (+ factors when available)."""
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=365 * years)

    df = None
    try:
        from services.model_train_service.data_loader import create_dataset, split_features_target

        df = create_dataset(
            tickers,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            horizon=5,
            include_factors=True,
        )
        if df is not None and len(df) >= 200 and "target" in df.columns:
            X, y = split_features_target(df)
            X = X.select_dtypes(include=[np.number]).replace([np.inf, -np.inf], np.nan).fillna(0.0)
            y = y.replace([np.inf, -np.inf], np.nan).fillna(0.0)
            logger.info(f"Dataset ready via data_loader: X={X.shape}, y={len(y)}")
            return X, y
    except Exception as exc:
        logger.warning(f"data_loader unavailable ({exc}); using local parquet fallback")

    # Minimal fallback from raw parquet without heavy service deps
    frames = []
    for t in tickers:
        path = DATA_DAILY / f"{t}.parquet"
        if not path.exists():
            continue
        raw = pd.read_parquet(path)
        raw.columns = [str(c).lower() for c in raw.columns]
        if "close" not in raw.columns:
            continue
        raw = raw.tail(504).copy()
        raw["ret_1"] = raw["close"].pct_change()
        raw["ret_5"] = raw["close"].pct_change(5)
        raw["ret_21"] = raw["close"].pct_change(21)
        raw["vol_21"] = raw["ret_1"].rolling(21).std()
        if "volume" in raw.columns:
            raw["vol_z"] = (raw["volume"] - raw["volume"].rolling(21).mean()) / raw["volume"].rolling(21).std().replace(0, np.nan)
        raw["target"] = raw["close"].pct_change(5).shift(-5)
        frames.append(raw)
    if not frames:
        raise RuntimeError("No training data available — download failed")
    df = pd.concat(frames, ignore_index=True).dropna()
    feature_cols = [c for c in df.select_dtypes(include=[np.number]).columns if c != "target"]
    X = df[feature_cols].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    y = df["target"].fillna(0.0)
    logger.info(f"Dataset ready via parquet fallback: X={X.shape}, y={len(y)}")
    return X, y


def train_one(model_name: str, X: pd.DataFrame, y: pd.Series, device: str, quick: bool) -> dict:
    """Train a single model and save under data/models/."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    metrics: dict = {}
    t0 = time.time()

    if model_name == "gbdt":
        from services.model_train_service.trainers.gbdt_trainer import GBDTTrainer

        trainer = GBDTTrainer(device=device)
        metrics = trainer.fit(
            X, y,
            n_estimators=50 if quick else 200,
            early_stopping_rounds=10 if quick else 20,
        )
        path = MODEL_DIR / "gbdt_v2.joblib"
        trainer.save(str(path))
    elif model_name == "transformer":
        from services.model_train_service.trainers.transformer_trainer import TransformerTrainer

        trainer = TransformerTrainer(device=device, d_model=64 if quick else None)
        metrics = trainer.fit(X, y, epochs=3 if quick else 15, batch_size=32)
        path = MODEL_DIR / "transformer_v2.pt"
        trainer.save(str(path))
    elif model_name == "tcn":
        from services.model_train_service.trainers.tcn_trainer import TCNTrainer

        trainer = TCNTrainer(device=device)
        metrics = trainer.fit(X, y, epochs=3 if quick else 20, batch_size=32)
        path = MODEL_DIR / "tcn_v2.pt"
        trainer.save(str(path))
    elif model_name == "tft":
        from services.model_train_service.trainers.tft_trainer import TFTTrainer

        trainer = TFTTrainer(device=device)
        metrics = trainer.fit(X, y, epochs=3 if quick else 15, batch_size=32)
        path = MODEL_DIR / "tft_v2.pt"
        trainer.save(str(path))
    elif model_name == "rl":
        from services.model_train_service.trainers.rl_trainer import RLTrainer

        trainer = RLTrainer(device=device)
        metrics = trainer.fit(
            X, y,
            rl_timesteps=2_000 if quick else 50_000,
            n_steps=256 if quick else 1024,
        )
        path = MODEL_DIR / "rl_v2.zip"
        trainer.save(str(path))
    else:
        raise ValueError(f"Unknown model: {model_name}")

    elapsed = round(time.time() - t0, 2)
    logger.info(f"✅ {model_name} done in {elapsed}s → {path} | {metrics}")
    return {"metrics": metrics, "path": str(path), "elapsed_s": elapsed}


def main() -> int:
    parser = argparse.ArgumentParser(description="Paper-mode model training pipeline")
    parser.add_argument("--models", default="gbdt", help="Comma list: gbdt,transformer,tcn,tft,rl")
    parser.add_argument("--tickers", default=",".join(DEFAULT_TICKERS))
    parser.add_argument("--years", type=int, default=2)
    parser.add_argument("--quick", action="store_true", help="Smoke training with tiny epochs")
    parser.add_argument("--skip-download", action="store_true")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Paper Training Pipeline")
    logger.info(f"  execution_mode={get_execution_mode()} sim={is_simulation_mode()}")
    logger.info(f"  train_device_env={settings.TRAIN_DEVICE}")
    logger.info("=" * 60)

    if get_execution_mode() != "paper":
        logger.error("Refusing to train outside paper mode — set QAT_TRADING_SIMULATION_MODE=true")
        return 2

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    models = [m.strip().lower() for m in args.models.split(",") if m.strip()]
    device = _resolve_device(settings.TRAIN_DEVICE)

    if not args.skip_download:
        n = download_ohlcv(tickers, years=args.years)
        logger.info(f"Downloaded {n} new parquet files")

    X, y = build_dataset(tickers, years=args.years)
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "paper",
        "device": device,
        "tickers": tickers,
        "data": {"rows": int(len(X)), "features": int(X.shape[1])},
        "models": {},
    }

    for name in models:
        try:
            report["models"][name] = train_one(name, X, y, device, args.quick)
            report["models"][name]["ok"] = True
        except Exception as exc:
            logger.exception(f"❌ {name} failed: {exc}")
            report["models"][name] = {"ok": False, "error": str(exc)}

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Report → {REPORT_PATH}")

    ok = all(v.get("ok") for v in report["models"].values()) if report["models"] else False
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
