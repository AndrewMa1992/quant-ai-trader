#!/usr/bin/env python3
"""
Pre-training script — run before first launch.
Downloads data and trains AI models.
"""
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from loguru import logger
from backend.ai_models.trainer import ModelTrainer


def main():
    """Entry point."""
    logger.info("=" * 60)
    logger.info("🧠 Quant AI Trader - Pre-training")
    logger.info("=" * 60)

    trainer = ModelTrainer()

    # Download data and train models
    trainer.train_all(tickers=["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"])

    logger.info("\n" + "=" * 60)
    logger.info("✅ Pre-training complete!")
    logger.info(f"   Transformer: {'ready' if trainer.transformer.is_ready() else 'failed'}")
    logger.info(f"   PPO Agent:   {'ready' if trainer.rl_agent.is_ready() else 'failed'}")

    summary = trainer.get_training_summary()
    logger.info("\n📊 Model files:")
    for k, v in summary.items():
        logger.info(f"   {k}: {v}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
