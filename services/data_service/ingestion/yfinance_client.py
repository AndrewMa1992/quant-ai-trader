"""services/data_service/ingestion/yfinance_client.py – yfinance wrapper.

Features:
- Daily OHLCV fetch with date range
- Ticker info lookup (name, sector, market cap)
- Rate limiting (≥ 2s between calls)
- Exponential backoff retry (max 3 attempts)
"""

from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf
from loguru import logger

from services.data_service.config import data_config
from shared.core.exceptions import DataFetchError


class YFinanceClient:
    """Async wrapper around yfinance for historical market data.

    Enforces rate limits and automatic retry with backoff.
    """

    def __init__(self) -> None:
        self._last_request_time: float = 0.0
        self._rate_limit = data_config.YFINANCE_RATE_LIMIT_SECONDS
        self._max_retries = data_config.YFINANCE_MAX_RETRIES
        self._backoff = data_config.YFINANCE_RETRY_BACKOFF

    async def _rate_limit_wait(self) -> None:
        """Enforce minimum interval between requests."""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self._rate_limit:
            wait = self._rate_limit - elapsed
            logger.debug(f"Rate limiting: waiting {wait:.1f}s")
            await asyncio.sleep(wait)
        self._last_request_time = time.monotonic()

    async def fetch_daily(
        self,
        ticker: str,
        start: date | None = None,
        end: date | None = None,
    ) -> Optional[pd.DataFrame]:
        """Fetch daily OHLCV bars from yfinance.

        Args:
            ticker: Stock ticker symbol (e.g. 'AAPL', '0700.HK').
            start: Start date for data fetch.
            end: End date for data fetch.

        Returns:
            DataFrame with columns: Open/High/Low/Close/Adj Close/Volume,
            indexed by Date. Returns None if no data.

        Raises:
            DataFetchError: If all retries are exhausted.
        """
        start = start or date.today() - timedelta(days=365 * data_config.BACKFILL_YEARS)
        end = end or date.today()

        last_exception: Exception | None = None
        current_delay = self._rate_limit

        for attempt in range(1, self._max_retries + 1):
            try:
                await self._rate_limit_wait()

                # Run yfinance in a thread to avoid blocking the event loop
                df = await asyncio.to_thread(
                    self._fetch_sync, ticker, start.isoformat(), end.isoformat()
                )

                if df is None or df.empty:
                    logger.warning(f"No data returned for {ticker} [{start} to {end}]")
                    return None

                # Standardize column names
                df.columns = [c.lower().replace(" ", "_") for c in df.columns]
                df.index.name = "date"

                logger.info(f"Fetched {len(df)} daily bars for {ticker} [{start} to {end}]")
                return df

            except Exception as e:
                last_exception = e
                if attempt < self._max_retries:
                    logger.warning(
                        f"yfinance fetch attempt {attempt}/{self._max_retries} "
                        f"failed for {ticker}: {e}. Retrying in {current_delay:.1f}s"
                    )
                    await asyncio.sleep(current_delay)
                    current_delay *= self._backoff
                else:
                    logger.error(
                        f"yfinance fetch exhausted for {ticker} after {self._max_retries} attempts"
                    )

        raise DataFetchError(
            f"Failed to fetch {ticker} after {self._max_retries} retries",
            details={"ticker": ticker, "error": str(last_exception)},
        )

    def _fetch_sync(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        """Synchronous yfinance download (runs in thread pool).

        Args:
            ticker: Stock ticker.
            start: ISO date string.
            end: ISO date string.

        Returns:
            DataFrame with OHLCV data.
        """
        stock = yf.Ticker(ticker)
        df = stock.history(start=start, end=end, auto_adjust=False)
        return df

    async def fetch_ticker_info(self, ticker: str) -> dict:
        """Fetch company information for a ticker.

        Args:
            ticker: Stock ticker symbol.

        Returns:
            Dictionary with name, sector, industry, market_cap, etc.
        """
        await self._rate_limit_wait()
        try:
            info = await asyncio.to_thread(self._fetch_info_sync, ticker)
            return info
        except Exception as e:
            logger.error(f"Failed to fetch ticker info for {ticker}: {e}")
            return {"ticker": ticker, "name": ticker, "error": str(e)}

    def _fetch_info_sync(self, ticker: str) -> dict:
        """Synchronous ticker info fetch."""
        stock = yf.Ticker(ticker)
        info = stock.info
        return {
            "ticker": ticker,
            "name": info.get("longName", info.get("shortName", ticker)),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "market_cap": info.get("marketCap"),
            "currency": info.get("currency", "USD"),
            "exchange": info.get("exchange", ""),
            "country": info.get("country", ""),
        }

    async def fetch_multi(
        self,
        tickers: list[str],
        start: date | None = None,
        end: date | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Fetch daily data for multiple tickers sequentially.

        Args:
            tickers: List of ticker symbols.
            start: Start date.
            end: End date.

        Returns:
            Dictionary mapping ticker → DataFrame.
        """
        results: dict[str, pd.DataFrame] = {}
        for i, ticker in enumerate(tickers):
            try:
                df = await self.fetch_daily(ticker, start, end)
                if df is not None and not df.empty:
                    results[ticker] = df
                logger.debug(f"[{i+1}/{len(tickers)}] Fetched {ticker}")
            except DataFetchError:
                logger.warning(f"[{i+1}/{len(tickers)}] Skipped {ticker} (fetch failed)")
                continue
        return results
