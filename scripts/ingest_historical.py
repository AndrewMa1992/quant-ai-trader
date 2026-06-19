#!/usr/bin/env python3
"""scripts/ingest_historical.py – Batch historical data ingestion.

Iterates through the market universe and downloads OHLCV data
from yfinance, cleans it, and stores as Parquet files.

Usage:
    python scripts/ingest_historical.py --market US
    python scripts/ingest_historical.py --tickers AAPL,MSFT,GOOGL
    python scripts/ingest_historical.py --years 10
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, timedelta

from loguru import logger

from configs.market_universe import MARKET_UNIVERSE, get_all_tickers
from services.data_service.ingestion.yfinance_client import YFinanceClient
from services.data_service.pipeline.cleanser import DataCleanser
from services.data_service.storage.metadata_store import MetadataStore
from services.data_service.storage.parquet_store import ParquetStore
from shared.core.helpers import chunked
from shared.core.logger import setup_logger


async def ingest(
    tickers: list[str],
    years: int = 5,
    batch_size: int = 20,
) -> dict[str, int]:
    """Batch ingest historical data for tickers.

    Args:
        tickers: List of ticker symbols.
        years: Number of years of history to download.
        batch_size: Number of tickers per concurrent batch.

    Returns:
        Dict with success/fail/skip counts.
    """
    yf = YFinanceClient()
    cleanser = DataCleanser()
    store = ParquetStore()
    meta = MetadataStore()

    end = date.today()
    start = end - timedelta(days=365 * years)

    success = 0
    failed = 0
    skipped = 0

    total = len(tickers)
    logger.info(f"Starting historical ingestion: {total} tickers, {years} years")

    for i, batch in enumerate(chunked(tickers, batch_size)):
        logger.info(f"Batch {i+1}/{(total + batch_size - 1) // batch_size}: {batch}")

        for ticker in batch:
            try:
                # Check if data already exists
                existing = store.read_daily(ticker)
                if existing is not None and len(existing) > 200:
                    logger.debug(f"  {ticker}: already cached ({len(existing)} bars)")
                    skipped += 1
                    continue

                # Fetch from yfinance
                df = await yf.fetch_daily(ticker, start, end)
                if df is None or df.empty:
                    logger.warning(f"  {ticker}: no data returned")
                    failed += 1
                    continue

                # Clean
                df = cleanser.clean(df, ticker)

                # Store
                store.write_daily(ticker, df)

                # Log quality
                score = cleanser.compute_quality_score(df)
                await meta.log_quality_check(
                    ticker=ticker,
                    source="yfinance",
                    bar_count=len(df),
                    quality_score=score,
                )

                logger.info(f"  {ticker}: {len(df)} bars (quality: {score:.2f})")
                success += 1

            except ValueError as e:
                logger.warning(f"  {ticker}: quality check failed - {e}")
                failed += 1
            except Exception as e:
                logger.error(f"  {ticker}: error - {e}")
                failed += 1

        # Rate limit between batches
        await asyncio.sleep(2.0)

    logger.info(f"Ingestion complete: {success} ok, {failed} fail, {skipped} skip")
    return {"success": success, "failed": failed, "skipped": skipped}


async def main() -> None:
    setup_logger()

    parser = argparse.ArgumentParser(description="Batch historical data ingestion")
    parser.add_argument("--market", type=str, help="Market code (US/HK/SG/AU/NZ)")
    parser.add_argument("--tickers", type=str, help="Comma-separated ticker list")
    parser.add_argument("--years", type=int, default=5, help="Years of history")
    parser.add_argument("--batch-size", type=int, default=20)
    args = parser.parse_args()

    if args.tickers:
        tickers = [t.strip() for t in args.tickers.split(",")]
    elif args.market:
        market = args.market.upper()
        if market not in MARKET_UNIVERSE:
            logger.error(f"Unknown market: {market}. Valid: {list(MARKET_UNIVERSE.keys())}")
            sys.exit(1)
        tickers = [s["ticker"] for s in MARKET_UNIVERSE[market]]
    else:
        tickers = get_all_tickers()

    logger.info(f"Target: {len(tickers)} tickers, {args.years} years")
    await ingest(tickers, years=args.years, batch_size=args.batch_size)


if __name__ == "__main__":
    asyncio.run(main())
