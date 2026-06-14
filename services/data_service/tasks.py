"""services/data_service/tasks.py – Scheduled data pipeline tasks.

Periodic jobs:
- daily_ingest: Fetch latest OHLCV for all universe tickers
- daily_cleanse: Run data quality checks
- daily_aggregate: Build weekly/monthly aggregations
- intraday_update: Fetch minute bars during market hours

Designed to be called by a scheduler (Celery, APScheduler, or cron).
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

import pandas as pd
from loguru import logger

from configs.market_universe import MARKET_UNIVERSE, get_all_tickers
from services.data_service.config import data_config
from services.data_service.ingestion.yfinance_client import YFinanceClient
from services.data_service.pipeline.aggregator import DataAggregator
from services.data_service.pipeline.cleanser import DataCleanser
from services.data_service.storage.metadata_store import MetadataStore
from services.data_service.storage.parquet_store import ParquetStore
from shared.core.helpers import chunked


class DataTasks:
    """Collection of scheduled data pipeline tasks."""

    def __init__(self) -> None:
        self.yf = YFinanceClient()
        self.cleanser = DataCleanser()
        self.store = ParquetStore()
        self.meta = MetadataStore()

    async def daily_ingest(self, tickers: list[str] | None = None) -> dict[str, int]:
        """Fetch latest daily bars for all (or specified) universe tickers.

        Args:
            tickers: Optional subset of tickers. Defaults to all universe tickers.

        Returns:
            Dict with success/failure counts.
        """
        tickers = tickers or get_all_tickers()
        today = date.today()
        start = today - timedelta(days=7)  # Fetch last week to fill gaps

        success = 0
        failed = 0
        skipped = 0

        logger.info(f"Starting daily ingest for {len(tickers)} tickers")

        for batch in chunked(tickers, 50):
            tasks = []
            for ticker in batch:
                tasks.append(self._ingest_single(ticker, start, today))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    failed += 1
                elif r == "success":
                    success += 1
                else:
                    skipped += 1

            # Rate limit between batches
            await asyncio.sleep(2.0)

        logger.info(f"Daily ingest complete: {success} ok, {failed} fail, {skipped} skip")
        return {"success": success, "failed": failed, "skipped": skipped}

    async def _ingest_single(self, ticker: str, start: date, end: date) -> str:
        """Ingest data for a single ticker.

        Args:
            ticker: Stock ticker.
            start: Start date.
            end: End date.

        Returns:
            'success', 'skipped', or raises on failure.
        """
        try:
            df = await self.yf.fetch_daily(ticker, start, end)
            if df is None or df.empty:
                return "skipped"

            df = self.cleanser.clean(df, ticker)
            self.store.write_daily(ticker, df)

            # Log quality
            score = self.cleanser.compute_quality_score(df)
            await self.meta.log_quality_check(
                ticker=ticker,
                source="yfinance",
                bar_count=len(df),
                quality_score=score,
            )
            return "success"
        except Exception as e:
            logger.error(f"Ingest failed for {ticker}: {e}")
            raise

    async def daily_cleanse(self) -> dict[str, int]:
        """Run quality checks on all stored tickers.

        Returns:
            Dict with pass/fail counts.
        """
        tickers = self.store.list_tickers()
        pass_count = 0
        fail_count = 0

        for ticker in tickers:
            try:
                df = self.store.read_daily(ticker)
                if df is None:
                    continue

                try:
                    self.cleanser.clean(df, ticker)
                    pass_count += 1
                except ValueError:
                    fail_count += 1
                    logger.warning(f"Quality check failed for {ticker}")
            except Exception as e:
                logger.error(f"Cleanse error for {ticker}: {e}")
                fail_count += 1

        logger.info(f"Daily cleanse: {pass_count} pass, {fail_count} fail")
        return {"pass": pass_count, "fail": fail_count}

    async def build_aggregations(self) -> None:
        """Build weekly and monthly aggregations from daily data."""
        tickers = self.store.list_tickers()
        count = 0

        for ticker in tickers:
            try:
                df = self.store.read_daily(ticker)
                if df is None or df.empty:
                    continue

                # Only process if we have enough data
                if len(df) < 20:
                    continue

                weekly = DataAggregator.daily_to_weekly(df)
                monthly = DataAggregator.daily_to_monthly(df)

                if not weekly.empty:
                    self.store.write_daily(f"{ticker}_W", weekly)
                if not monthly.empty:
                    self.store.write_daily(f"{ticker}_M", monthly)

                count += 1
            except Exception as e:
                logger.error(f"Aggregation failed for {ticker}: {e}")

        logger.info(f"Built aggregations for {count} tickers")

    async def intraday_update(self, tickers: list[str] | None = None) -> None:
        """Fetch latest minute bars during market hours.

        Args:
            tickers: Tickers to update. Defaults to US market.
        """
        tickers = tickers or [s["ticker"] for s in MARKET_UNIVERSE.get("US", [])[:50]]
        today = date.today()

        for ticker in tickers:
            try:
                df = await self.yf.fetch_daily(ticker, today - timedelta(days=1), today)
                if df is not None and not df.empty:
                    self.store.write_daily(ticker, df)
            except Exception as e:
                logger.error(f"Intraday update failed for {ticker}: {e}")

        logger.info(f"Intraday update complete for {len(tickers)} tickers")


# Convenience functions for direct invocation
_data_tasks = DataTasks()


async def run_daily_ingest() -> dict[str, int]:
    """Run the daily data ingestion task."""
    return await _data_tasks.daily_ingest()


async def run_daily_cleanse() -> dict[str, int]:
    """Run the daily data quality check."""
    return await _data_tasks.daily_cleanse()


async def run_build_aggregations() -> None:
    """Build weekly/monthly aggregations."""
    await _data_tasks.build_aggregations()
