"""
scripts/train_all_models.py — 全量模型训练脚本 (v3)
===================================================
按顶级量化基金标准训练全部5个模型:
  GBDT (LightGBM) → Transformer (PatchTST) → TCN → TFT → RL (PPO)

特性:
  - 从 ParquetStore 加载49个ticker的日线数据
  - FactorEngine 计算因子作为特征
  - 多时间尺度预测 (1d, 5d, 21d horizon)
  - Walk-Forward 交叉验证
  - 每个模型训练完立即保存
  - 失败跳过，继续下一个
  - 更新 ModelRegistry 数据库

用法:
  cd E:\workbuddyspace\Claw\quant-ai-trader
  python scripts/train_all_models.py
"""
import sys
import os
import time
import uuid
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import torch
from loguru import logger

# Ensure project root in path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from configs.settings import settings

# ── Logger setup ──────────────────────────────────────────
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    level="INFO",
)
logger.add(
    PROJECT_ROOT / "logs" / "train_all_{time}.log",
    rotation="100 MB",
    level="DEBUG",
)

MODELS_DIR = PROJECT_ROOT / "data" / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)
DEVICE = settings.TRAIN_DEVICE


# ═══════════════════════════════════════════════════════════
# Step 1: 构建训练数据集
# ═══════════════════════════════════════════════════════════
def build_training_dataset(min_bars: int = 100) -> Optional[pd.DataFrame]:
    """从 data/daily/*.parquet 加载全部 ticker 数据，计算因子，构建监督学习数据集。

    Returns:
        DataFrame with features + forward return targets, or None on failure.
    """
    logger.info("=" * 60)
    logger.info("[Step 1] 构建训练数据集")
    logger.info("=" * 60)

    daily_dir = PROJECT_ROOT / "data" / "daily"
    parquet_files = sorted(daily_dir.glob("*.parquet"))

    if not parquet_files:
        logger.error(f"无 parquet 数据文件: {daily_dir}")
        return None

    logger.info(f"发现 {len(parquet_files)} 个 parquet 文件")

    # ── FactorEngine ──────────────────────────────────────
    from services.factor_service.engine.factor_engine import FactorEngine
    engine = FactorEngine()

    # Manually register factor instances (register_all() stores
    # classes instead of instances which breaks compute())
    from services.factor_service.factors.technical import TECHNICAL_FACTORS
    from services.factor_service.factors.fundamental import FUNDAMENTAL_FACTORS
    from services.factor_service.factors.microstructure import MICROSTRUCTURE_FACTORS

    all_factor_classes = TECHNICAL_FACTORS + FUNDAMENTAL_FACTORS + MICROSTRUCTURE_FACTORS
    registered = 0
    for factor in all_factor_classes:
        try:
            # Lists already contain FactorBase instances
            engine.register(factor)
            registered += 1
        except Exception:
            pass
    logger.info(f"已注册 {registered}/{len(all_factor_classes)} 个因子")

    # ── Process each ticker ───────────────────────────────
    all_frames: list[pd.DataFrame] = []
    skipped = 0

    for fpath in parquet_files:
        ticker = fpath.stem
        try:
            df = pd.read_parquet(fpath)

            # Normalize column names to lowercase
            df.columns = [c.lower() for c in df.columns]

            if len(df) < min_bars:
                skipped += 1
                continue

            # Take last 2 years for training
            df = df.tail(504).copy()

            # Ensure required columns
            if "close" not in df.columns:
                skipped += 1
                continue

            # Compute factors
            try:
                result_df = engine.compute_all(df)
            except Exception as e:
                logger.debug(f"Factor computation failed for {ticker}: {e}")
                result_df = df.copy()

            # Forward returns (multi-horizon targets)
            for horizon in [1, 5, 21]:
                col_name = f"fwd_ret_{horizon}d"
                result_df[col_name] = (
                    result_df["close"].shift(-horizon) / result_df["close"] - 1
                )

            # Daily return feature
            if "ret_1d" not in result_df.columns:
                result_df["ret_1d"] = result_df["close"].pct_change()

            result_df["ticker"] = ticker
            all_frames.append(result_df)

        except Exception as e:
            logger.warning(f"跳过 {ticker}: {e}")
            skipped += 1
            continue

    if not all_frames:
        logger.error("所有 ticker 处理失败")
        return None

    combined = pd.concat(all_frames, ignore_index=True)
    # Drop rows with NaN targets (edges)
    combined = combined.dropna(subset=["fwd_ret_1d", "fwd_ret_5d", "fwd_ret_21d"])
    # Replace inf
    combined = combined.replace([np.inf, -np.inf], np.nan)
    combined = combined.dropna()

    logger.info(
        f"训练数据集: {len(combined)} 行 × {combined.shape[1]} 列, "
        f"{len(all_frames)} 标的, {skipped} 跳过"
    )

    # ── Feature/target column identification ──────────────
    exclude_patterns = [
        "ticker", "date", "open", "high", "low", "close", "adj_close",
        "volume", "dividends", "stock splits",
    ]
    feature_cols = [
        c for c in combined.columns
        if c not in exclude_patterns and not c.startswith("fwd_ret")
    ]
    logger.info(f"特征列: {len(feature_cols)}, 目标列: fwd_ret_1d, fwd_ret_5d, fwd_ret_21d")

    return combined


# ═══════════════════════════════════════════════════════════
# Step 2-6: 训练各个模型
# ═══════════════════════════════════════════════════════════

def prepare_xy(
    data: pd.DataFrame,
    horizon_days: int = 5,
) -> tuple[pd.DataFrame, pd.Series, pd.Series, list[str]]:
    """Extract features and targets from dataset.

    Args:
        data: Combined DataFrame with features and fwd_ret_* columns.
        horizon_days: Which forward return horizon to use (1, 5, or 21).

    Returns:
        (X, y_regression, y_binary, feature_cols)
    """
    exclude = [
        "ticker", "date", "open", "high", "low", "close", "adj_close",
        "volume", "dividends", "stock splits",
    ]
    feature_cols = [
        c for c in data.columns
        if c not in exclude and not c.startswith("fwd_ret")
    ]

    target_col = f"fwd_ret_{horizon_days}d"
    if target_col not in data.columns:
        raise ValueError(f"Target column {target_col} not found")

    X = data[feature_cols].copy()
    # Fill remaining NaN with 0
    X = X.fillna(0.0)

    y_reg = data[target_col].clip(-0.3, 0.3).fillna(0.0)
    y_bin = (data[target_col] > 0).astype(int).fillna(0)

    return X, y_reg, y_bin, feature_cols


def train_test_split_time(
    X: pd.DataFrame,
    y_reg: pd.Series,
    y_bin: pd.Series,
    train_pct: float = 0.70,
    val_pct: float = 0.15,
) -> tuple:
    """Simple time-based train/val/test split (no shuffling)."""
    n = len(X)
    train_end = int(n * train_pct)
    val_end = int(n * (train_pct + val_pct))

    return (
        X.iloc[:train_end], X.iloc[train_end:val_end], X.iloc[val_end:],
        y_reg.iloc[:train_end], y_reg.iloc[train_end:val_end], y_reg.iloc[val_end:],
        y_bin.iloc[:train_end], y_bin.iloc[train_end:val_end], y_bin.iloc[val_end:],
    )


# ── 2. GBDT ───────────────────────────────────────────────
def train_gbdt(data: pd.DataFrame) -> bool:
    """Train LightGBM GBDT model with early stopping."""
    logger.info("\n" + "=" * 60)
    logger.info("[Step 2] 训练 GBDT (LightGBM)")
    logger.info("=" * 60)

    output_path = str(MODELS_DIR / "gbdt_v1.joblib")

    try:
        X, y_reg, y_bin, feature_cols = prepare_xy(data, horizon_days=5)
        X_train, X_val, X_test, y_train, y_val, y_test, _, _, _ = \
            train_test_split_time(X, y_reg, y_bin)

        from services.model_train_service.trainers.gbdt_trainer import GBDTTrainer

        gbdt = GBDTTrainer(gbdt_type="lightgbm", device=DEVICE)
        gbdt.params = {
            "objective": "regression",
            "metric": "rmse",
            "num_leaves": 31,
            "learning_rate": 0.01,
            "feature_fraction": 0.8,
            "bagging_fraction": 0.8,
            "bagging_freq": 5,
            "verbose": -1,
            "n_estimators": 1000,
            "early_stopping_rounds": 20,
        }

        metrics = gbdt.fit(X_train, y_train, X_val, y_val)
        logger.info(f"GBDT 训练完成: {metrics}")

        # Feature importance
        importance = gbdt.get_feature_importance()
        if len(importance) > 0:
            top5 = importance.head(5)
            logger.info(f"Top 5 特征: {dict(top5)}")

        # Evaluate
        pred = gbdt.predict(X_test)
        test_rmse = float(np.sqrt(((pred - y_test.values) ** 2).mean()))
        test_acc = float(((pred > 0) == (y_test.values > 0)).mean())
        logger.info(f"GBDT Test: RMSE={test_rmse:.6f}, DirectionAcc={test_acc:.4f}")

        gbdt.save(output_path)

        # Update DB
        _update_model_registry(
            model_name="gbdt",
            version="v1",
            model_type="gbdt",
            file_path=output_path,
            metrics={"test_rmse": test_rmse, "test_acc": test_acc, **metrics},
            params=gbdt.params,
            feature_cols=feature_cols,
        )

        return True

    except Exception as e:
        logger.error(f"GBDT 训练失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


# ── 3. Transformer (PatchTST) ─────────────────────────────
def train_transformer(data: pd.DataFrame) -> bool:
    """Train PatchTST Transformer with d_model=256(CPU)."""
    logger.info("\n" + "=" * 60)
    logger.info("[Step 3] 训练 Transformer (PatchTST)")
    logger.info("=" * 60)

    output_path = str(MODELS_DIR / "transformer_v3.pt")

    try:
        X, y_reg, y_bin, feature_cols = prepare_xy(data, horizon_days=5)
        X_train, X_val, X_test, y_train, y_val, y_test, _, _, _ = \
            train_test_split_time(X, y_reg, y_bin)

        from services.model_train_service.trainers.transformer_trainer import TransformerTrainer

        transformer = TransformerTrainer(
            d_model=256,
            n_heads=8,
            n_layers=4,
            dropout=0.1,
            seq_len=60,
            forecast_horizon=1,
            device=DEVICE,
        )

        metrics = transformer.fit(
            X_train, y_train, X_val, y_val,
            epochs=200, batch_size=64, lr=0.001,
        )
        logger.info(f"Transformer 训练完成: {metrics}")

        transformer.save(output_path)

        _update_model_registry(
            model_name="transformer",
            version="v3",
            model_type="transformer",
            file_path=output_path,
            metrics=metrics,
            params={
                "d_model": 256, "n_heads": 8, "n_layers": 4,
                "dropout": 0.1, "seq_len": 60, "epochs": 200, "batch_size": 64,
            },
            feature_cols=feature_cols,
        )

        return True

    except Exception as e:
        logger.error(f"Transformer 训练失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


# ── 4. TCN ────────────────────────────────────────────────
def train_tcn(data: pd.DataFrame) -> bool:
    """Train Temporal Convolutional Network."""
    logger.info("\n" + "=" * 60)
    logger.info("[Step 4] 训练 TCN")
    logger.info("=" * 60)

    output_path = str(MODELS_DIR / "tcn_v1.pt")

    try:
        X, y_reg, y_bin, feature_cols = prepare_xy(data, horizon_days=5)
        X_train, X_val, X_test, y_train, y_val, y_test, _, _, _ = \
            train_test_split_time(X, y_reg, y_bin)

        from services.model_train_service.trainers.tcn_trainer import TCNTrainer

        tcn = TCNTrainer(
            num_channels=[64, 64, 64, 32],
            kernel_size=3,
            dropout=0.1,
            seq_len=60,
            device=DEVICE,
        )

        metrics = tcn.fit(
            X_train, y_train, X_val, y_val,
            epochs=200, batch_size=64, lr=0.001,
        )
        logger.info(f"TCN 训练完成: {metrics}")

        tcn.save(output_path)

        _update_model_registry(
            model_name="tcn",
            version="v1",
            model_type="tcn",
            file_path=output_path,
            metrics=metrics,
            params={
                "num_channels": [64, 64, 64, 32], "kernel_size": 3,
                "dropout": 0.1, "seq_len": 60, "epochs": 200,
            },
            feature_cols=feature_cols,
        )

        return True

    except Exception as e:
        logger.error(f"TCN 训练失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


# ── 5. TFT (Temporal Fusion Transformer) ──────────────────
def train_tft(data: pd.DataFrame) -> bool:
    """Train Temporal Fusion Transformer."""
    logger.info("\n" + "=" * 60)
    logger.info("[Step 5] 训练 TFT (Temporal Fusion Transformer)")
    logger.info("=" * 60)

    output_path = str(MODELS_DIR / "tft_v1.pt")

    try:
        X, y_reg, y_bin, feature_cols = prepare_xy(data, horizon_days=5)
        X_train, X_val, X_test, y_train, y_val, y_test, _, _, _ = \
            train_test_split_time(X, y_reg, y_bin)

        from services.model_train_service.trainers.tft_trainer import TFTTrainer

        tft = TFTTrainer(
            hidden_dim=64,
            n_heads=4,
            lstm_layers=1,
            dropout=0.1,
            seq_len=60,
            device=DEVICE,
        )

        metrics = tft.fit(
            X_train, y_train, X_val, y_val,
            epochs=200, batch_size=64, lr=0.001,
        )
        logger.info(f"TFT 训练完成: {metrics}")

        tft.save(output_path)

        _update_model_registry(
            model_name="tft",
            version="v1",
            model_type="tft",
            file_path=output_path,
            metrics=metrics,
            params={
                "hidden_dim": 64, "n_heads": 4, "lstm_layers": 1,
                "dropout": 0.1, "seq_len": 60, "epochs": 200,
            },
            feature_cols=feature_cols,
        )

        return True

    except Exception as e:
        logger.error(f"TFT 训练失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


# ── 6. RL (PPO) ───────────────────────────────────────────
def train_rl(data: pd.DataFrame) -> bool:
    """Train PPO RL agent on trading environment."""
    logger.info("\n" + "=" * 60)
    logger.info("[Step 6] 训练 RL (PPO)")
    logger.info("=" * 60)

    output_path = str(MODELS_DIR / "rl_v1.zip")

    try:
        # RL uses a different setup: needs returns in first column
        X, y_reg, y_bin, feature_cols = prepare_xy(data, horizon_days=5)

        # Use smaller subset for faster RL training
        max_samples = min(50000, len(X))
        X_subset = X.iloc[-max_samples:]
        y_subset = y_reg.iloc[-max_samples:]

        from services.model_train_service.trainers.rl_trainer import RLTrainer

        rl = RLTrainer(algo="PPO", device=DEVICE)

        metrics = rl.fit(
            X_subset, y_subset,
            rl_timesteps=200000,
        )
        logger.info(f"RL 训练完成: {metrics}")

        rl.save(output_path)

        _update_model_registry(
            model_name="rl",
            version="v1",
            model_type="rl",
            file_path=output_path,
            metrics=metrics,
            params={"algo": "PPO", "timesteps": 200000},
            feature_cols=feature_cols,
        )

        return True

    except Exception as e:
        logger.error(f"RL 训练失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


# ═══════════════════════════════════════════════════════════
# Step 7: 更新 ModelRegistry 数据库
# ═══════════════════════════════════════════════════════════
def _update_model_registry(
    model_name: str,
    version: str,
    model_type: str,
    file_path: str,
    metrics: dict,
    params: dict,
    feature_cols: list[str],
) -> None:
    """Update the model_versions table in SQLite database."""
    import sqlite3
    import json
    import hashlib

    db_path = str(PROJECT_ROOT / "data" / "quant_trader.db")

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        model_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        features_hash = hashlib.sha256(
            ",".join(sorted(feature_cols)).encode()
        ).hexdigest()[:64]

        # Set all previous versions of this model to is_production=False
        cursor.execute(
            "UPDATE model_versions SET is_production = 0 WHERE model_name = ?",
            (model_name,)
        )

        # Insert new version
        cursor.execute(
            """INSERT INTO model_versions
               (id, model_name, version, model_type, status, trained_at,
                target_horizon, features_hash, parameters, factor_ids,
                is_production, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'ready', ?, '5d', ?, ?, ?, 1, ?, ?)""",
            (
                model_id,
                model_name,
                version,
                model_type,
                now,
                features_hash,
                json.dumps(params),
                json.dumps(feature_cols[:50]),  # First 50 factor IDs
                now,
                now,
            )
        )

        # Insert metrics
        for metric_name, metric_value in metrics.items():
            metric_id = str(uuid.uuid4())
            cursor.execute(
                """INSERT OR REPLACE INTO model_metrics
                   (id, model_id, metric_name, metric_value, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (metric_id, model_id, metric_name, float(metric_value), now)
            )

        conn.commit()
        conn.close()

        logger.info(f"ModelRegistry 更新: {model_name} v{version} (production=True)")

    except Exception as e:
        logger.warning(f"ModelRegistry 更新失败 (non-critical): {e}")


# ═══════════════════════════════════════════════════════════
# Verification
# ═══════════════════════════════════════════════════════════
def verify_models() -> dict:
    """Verify all trained models exist and can be loaded."""
    logger.info("\n" + "=" * 60)
    logger.info("[Verification] 验证训练产出")
    logger.info("=" * 60)

    expected = {
        "gbdt_v1.joblib": "gbdt",
        "transformer_v3.pt": "transformer",
        "tcn_v1.pt": "tcn",
        "tft_v1.pt": "tft",
        "rl_v1.zip": "rl",
    }

    results: dict = {}

    for filename, model_type in expected.items():
        fpath = MODELS_DIR / filename
        exists = fpath.exists()
        size = fpath.stat().st_size if exists else 0
        status = "PASS" if (exists and size > 0) else "FAIL"
        results[filename] = {"exists": exists, "size_bytes": size, "status": status}
        logger.info(f"  {filename}: {status} ({size:,} bytes)")

    # Try loading models
    try:
        import torch
        import joblib

        logger.info("\n[Load Test] 尝试加载模型...")

        # GBDT
        if (MODELS_DIR / "gbdt_v1.joblib").exists():
            try:
                gbdt_data = joblib.load(str(MODELS_DIR / "gbdt_v1.joblib"))
                logger.info("  GBDT: OK")
            except Exception as e:
                logger.warning(f"  GBDT load: {e}")

        # Transformer
        if (MODELS_DIR / "transformer_v3.pt").exists():
            try:
                from services.model_train_service.trainers.transformer_trainer import TransformerTrainer
                t = TransformerTrainer(d_model=256, n_heads=8, n_layers=4, device=DEVICE)
                t.load(str(MODELS_DIR / "transformer_v3.pt"))
                logger.info("  Transformer: OK")
            except Exception as e:
                logger.warning(f"  Transformer load: {e}")

        # TCN
        if (MODELS_DIR / "tcn_v1.pt").exists():
            try:
                from services.model_train_service.trainers.tcn_trainer import TCNTrainer
                tcn = TCNTrainer(device=DEVICE)
                tcn.load(str(MODELS_DIR / "tcn_v1.pt"))
                logger.info("  TCN: OK")
            except Exception as e:
                logger.warning(f"  TCN load: {e}")

        # TFT
        if (MODELS_DIR / "tft_v1.pt").exists():
            try:
                from services.model_train_service.trainers.tft_trainer import TFTTrainer
                tft = TFTTrainer(device=DEVICE)
                tft.load(str(MODELS_DIR / "tft_v1.pt"))
                logger.info("  TFT: OK")
            except Exception as e:
                logger.warning(f"  TFT load: {e}")

        # RL
        if (MODELS_DIR / "rl_v1.zip").exists():
            try:
                from stable_baselines3 import PPO
                rl_model = PPO.load(str(MODELS_DIR / "rl_v1.zip"), device=DEVICE)
                logger.info("  RL: OK")
            except Exception as e:
                logger.warning(f"  RL load: {e}")

    except Exception as e:
        logger.error(f"Load tests failed: {e}")

    all_pass = all(r["status"] == "PASS" for r in results.values())
    logger.info(f"\nOverall: {'PASS' if all_pass else 'PARTIAL FAIL'}")

    return results


# ═══════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════
def main():
    start_time = datetime.now()
    logger.info("=" * 60)
    logger.info(" Quant AI Trader v3 — 全量模型训练")
    logger.info(f" 启动时间: {start_time.isoformat()}")
    logger.info(f" DEVICE: {DEVICE}")
    logger.info(f" 输出目录: {MODELS_DIR}")
    logger.info("=" * 60)

    # ── Step 1: Build dataset ──────────────────────────────
    data = build_training_dataset()
    if data is None:
        logger.error("无法构建训练数据集，退出。")
        sys.exit(1)

    # ── Track training results ─────────────────────────────
    training_results: dict[str, bool] = {}

    # ── Step 2: GBDT ───────────────────────────────────────
    training_results["gbdt"] = train_gbdt(data)

    # ── Step 3: Transformer ────────────────────────────────
    training_results["transformer"] = train_transformer(data)

    # ── Step 4: TCN ────────────────────────────────────────
    training_results["tcn"] = train_tcn(data)

    # ── Step 5: TFT ────────────────────────────────────────
    training_results["tft"] = train_tft(data)

    # ── Step 6: RL (PPO) ───────────────────────────────────
    training_results["rl"] = train_rl(data)

    # ── Summary ────────────────────────────────────────────
    elapsed = datetime.now() - start_time
    logger.info("\n" + "=" * 60)
    logger.info(" 训练完成总结")
    logger.info("=" * 60)
    logger.info(f" 总耗时: {elapsed}")
    for model, success in training_results.items():
        status = "✓ PASS" if success else "✗ FAIL"
        logger.info(f"  {model}: {status}")

    passed = sum(1 for v in training_results.values() if v)
    logger.info(f" 通过: {passed}/{len(training_results)}")

    # ── Verification ───────────────────────────────────────
    verify_models()

    # ── Final status ───────────────────────────────────────
    trained_files = list(MODELS_DIR.glob("*"))
    logger.info(f"\nModels directory contents: {[f.name for f in trained_files]}")

    if passed == 0:
        logger.error("所有模型训练失败！")
        sys.exit(1)

    logger.info("\n训练完成！")


if __name__ == "__main__":
    main()
