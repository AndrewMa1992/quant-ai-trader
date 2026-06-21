"""scripts/train_tcn_tft_rl.py – Train TCN, TFT, and RL models and save to data/models/.

Usage:
    python scripts/train_tcn_tft_rl.py
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

from services.model_train_service.data_loader import create_dataset, split_features_target
from services.model_train_service.trainers.tcn_trainer import TCNTrainer
from services.model_train_service.trainers.tft_trainer import TFTTrainer
from services.model_train_service.trainers.rl_trainer import RLTrainer
from shared.core.logger import setup_logger

MODEL_DIR = Path("data/models")
MODEL_DIR.mkdir(parents=True, exist_ok=True)

# All available tickers
TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "SPY",
    "AVGO", "AMD", "ADBE", "CRM", "ORCL", "INTC", "CSCO", "QCOM",
    "IBM", "NOW", "INTU", "PLTR", "SNOW",
    "JPM", "V", "MA", "BAC", "WFC", "GS", "MS", "BLK", "C", "AXP", "SCHW", "SPGI", "CB",
    "UNH", "JNJ", "LLY", "PFE", "ABBV", "MRK", "TMO", "ABT", "DHR", "BMY", "AMGN",
    "ISRG", "GILD", "VRTX", "REGN",
]


def train_tcn() -> dict:
    """Train TCN model."""
    logger.info("=== Training TCN ===")
    t0 = time.time()

    df = create_dataset(
        tickers=TICKERS[:20],  # Use first 20 tickers for speed
        start_date="2024-01-01",
        end_date="2026-05-31",
    )
    if df is None or len(df) < 100:
        return {"status": "failed", "error": "Insufficient data"}

    features, target = split_features_target(df)
    trainer = TCNTrainer()

    try:
        metrics = trainer.fit(features, target, epochs=30, batch_size=64)
        trainer.save(str(MODEL_DIR / "tcn_v2.pt"))

        elapsed = time.time() - t0
        logger.info(f"TCN training complete in {elapsed:.1f}s: {metrics}")
        return {"status": "completed", "metrics": metrics, "elapsed_sec": round(elapsed, 1)}
    except Exception as e:
        logger.exception(f"TCN training failed: {e}")
        return {"status": "failed", "error": str(e)}


def train_tft() -> dict:
    """Train TFT model."""
    logger.info("=== Training TFT ===")
    t0 = time.time()

    df = create_dataset(
        tickers=TICKERS[:15],
        start_date="2024-01-01",
        end_date="2026-05-31",
    )
    if df is None or len(df) < 100:
        return {"status": "failed", "error": "Insufficient data"}

    features, target = split_features_target(df)
    trainer = TFTTrainer()

    try:
        metrics = trainer.fit(features, target, epochs=30, batch_size=64)
        trainer.save(str(MODEL_DIR / "tft_v2.pt"))

        elapsed = time.time() - t0
        logger.info(f"TFT training complete in {elapsed:.1f}s: {metrics}")
        return {"status": "completed", "metrics": metrics, "elapsed_sec": round(elapsed, 1)}
    except Exception as e:
        logger.exception(f"TFT training failed: {e}")
        return {"status": "failed", "error": str(e)}


def train_rl() -> dict:
    """Train RL (PPO) model."""
    logger.info("=== Training RL (PPO) ===")
    t0 = time.time()

    df = create_dataset(
        tickers=["SPY"],
        start_date="2024-01-01",
        end_date="2026-05-31",
    )
    if df is None or len(df) < 100:
        return {"status": "failed", "error": "Insufficient data"}

    features, target = split_features_target(df)
    trainer = RLTrainer(algo="PPO")

    try:
        metrics = trainer.fit(features, target)
        trainer.save(str(MODEL_DIR / "rl_v2.zip"))

        elapsed = time.time() - t0
        logger.info(f"RL training complete in {elapsed:.1f}s: {metrics}")
        return {"status": "completed", "metrics": metrics, "elapsed_sec": round(elapsed, 1)}
    except Exception as e:
        logger.exception(f"RL training failed: {e}")
        return {"status": "failed", "error": str(e)}


def main() -> None:
    setup_logger()

    results: dict[str, dict] = {}

    # Train TCN
    results["tcn"] = train_tcn()

    # Train TFT
    results["tft"] = train_tft()

    # Train RL
    results["rl"] = train_rl()

    # Summary
    print("\n" + "=" * 60)
    print("TRAINING RESULTS")
    print("=" * 60)
    for model_name, result in results.items():
        status = result.get("status", "unknown")
        metrics = result.get("metrics", {})
        elapsed = result.get("elapsed_sec", "?")
        print(f"  {model_name.upper():>6s}: {status:<10s} | {elapsed:>6}s | {metrics}")
    print("=" * 60)

    # Verify model files
    print("\nModel files:")
    for p in sorted(MODEL_DIR.glob("*")):
        print(f"  {p.name} ({p.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
