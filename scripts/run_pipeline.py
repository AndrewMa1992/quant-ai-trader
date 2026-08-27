"""
Trading Pipeline launcher — replaces v1 auto_trader.py
======================================================
Start the six-microservice trading pipeline and run T+0 cycles on a schedule.
"""
import asyncio
import sys
from pathlib import Path

# Ensure project root is on sys.path for absolute imports
PROJ_ROOT = Path(__file__).resolve().parent.parent
if str(PROJ_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJ_ROOT))

from loguru import logger

from trading_pipeline import TradingPipeline
from configs.pipeline_config import pipeline_config

# Logging config
logger.add(
    "logs/pipeline_{time}.log",
    rotation="1 day",
    retention="30 days",
    level="INFO",
    format="{time:ISO} | {level: <8} | pipeline | {message}",
)


async def main() -> None:
    """Start the trading pipeline main loop."""
    logger.info("=" * 60)
    logger.info("Quant AI Trader v2 — Trading Pipeline starting")
    logger.info(f"  Cycle Interval: {pipeline_config.CYCLE_INTERVAL_SECONDS}s")
    logger.info(f"  Trading Hours Only: {pipeline_config.TRADING_HOURS_ONLY}")
    logger.info(f"  Max Tickers/Cycle: {pipeline_config.MAX_TICKERS_PER_CYCLE}")
    logger.info(f"  Risk Checks: {pipeline_config.ENABLE_RISK_CHECKS}")
    logger.info(f"  Portfolio Opt: {pipeline_config.ENABLE_PORTFOLIO_OPT}")
    logger.info(f"  Service URLs: {pipeline_config.SERVICE_BASE_URLS}")
    logger.info("=" * 60)

    pipeline = TradingPipeline(pipeline_config)
    await pipeline.run(interval_seconds=pipeline_config.CYCLE_INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⏹ Stop signal received, pipeline closed")
    except Exception as e:
        logger.exception(f"❌ Pipeline exited with error: {e}")
        sys.exit(1)
