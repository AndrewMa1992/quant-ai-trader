"""
Trading Pipeline 启动脚本 — 替代 v1 auto_trader.py
==================================================
启动六微服务交易管线，定时执行 T+0 交易周期。
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

# 日志配置
logger.add(
    "logs/pipeline_{time}.log",
    rotation="1 day",
    retention="30 days",
    level="INFO",
    format="{time:ISO} | {level: <8} | pipeline | {message}",
)


async def main() -> None:
    """启动交易管线主循环。"""
    logger.info("=" * 60)
    logger.info("Quant AI Trader v2 — Trading Pipeline 启动")
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
        logger.info("⏹ 收到停止信号，管线已关闭")
    except Exception as e:
        logger.exception(f"❌ 管线异常退出: {e}")
        sys.exit(1)
