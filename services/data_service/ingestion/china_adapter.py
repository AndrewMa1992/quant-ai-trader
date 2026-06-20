"""services/data_service/ingestion/china_adapter.py – China A-share multi-source adapter.

Implements the Strategy Pattern with multi-level fallback for fetching
Chinese A-share historical data. After yfinance fails, tries Eastmoney
then Tencent Finance in sequence.

Auto-converts ticker formats: '000001' ↔ '000001.SZ' / '000001.SH'
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd
from loguru import logger

from services.data_service.ingestion.eastmoney_client import EastmoneyClient
from services.data_service.ingestion.tencent_client import TencentClient


class ChinaDataAdapter:
    """Multi-source adapter for Chinese A-share market data.

    Implements a Strategy Pattern fallback chain:
    1. Eastmoney (primary for A-shares)
    2. Tencent Finance (secondary fallback)

    Also handles ticker format normalization between numeric codes
    and exchange-suffixed formats.

    Attributes:
        fallbacks: Ordered list of (name, client) tuples for fallback.
    """

    # Shanghai prefixes for auto-detection
    SH_PREFIXES: frozenset[str] = frozenset(
        {"60", "68", "900", "51", "56", "58", "110", "113", "118", "128"}
    )

    def __init__(self) -> None:
        self.fallbacks: list[tuple[str, object]] = [
            ("eastmoney", EastmoneyClient()),
            ("tencent", TencentClient()),
        ]

    @staticmethod
    def normalize_ticker(ticker: str) -> str:
        """Normalize a ticker to the format expected by downstream clients.

        Args:
            ticker: Raw ticker (e.g. '000001', '000001.SZ', '600519.SH').

        Returns:
            Normalized ticker with exchange suffix preserved.
        """
        clean = ticker.upper().strip()

        # Already has exchange suffix
        if ".SZ" in clean or ".SH" in clean or ".HK" in clean:
            return clean

        # Pure 6-digit: auto-detect exchange
        if clean.isdigit() and len(clean) == 6:
            prefix = clean[:2]
            if prefix in ChinaDataAdapter.SH_PREFIXES:
                return f"{clean}.SH"
            return f"{clean}.SZ"

        return clean

    @staticmethod
    def is_china_ticker(ticker: str) -> bool:
        """Check if a ticker is likely a Chinese A-share.

        Args:
            ticker: Raw ticker symbol.

        Returns:
            True if the ticker matches A-share patterns.
        """
        clean = ticker.upper().strip()
        if ".SZ" in clean or ".SH" in clean:
            return True
        # 6-digit numeric → A-share
        if clean.isdigit() and len(clean) == 6:
            return True
        return False

    def fetch_history(
        self,
        ticker: str,
        start: str | date | None = None,
        end: str | date | None = None,
    ) -> Optional[pd.DataFrame]:
        """Fetch historical data with multi-level fallback.

        Strategy:
        1. Normalize ticker format
        2. Try Eastmoney → Tencent in order
        3. Return first successful result or None

        Args:
            ticker: Raw ticker symbol.
            start: Start date filter.
            end: End date filter.

        Returns:
            DataFrame with OHLCV columns and date index, or None.
        """
        normalized = self.normalize_ticker(ticker)
        logger.debug(f"ChinaDataAdapter: {ticker} → normalized={normalized}")

        for source_name, client in self.fallbacks:
            try:
                df = client.fetch_history(normalized, start=start, end=end)
                if df is not None and not df.empty:
                    logger.info(
                        f"ChinaDataAdapter: {ticker} resolved via {source_name} "
                        f"({len(df)} bars)"
                    )
                    return df
                logger.debug(
                    f"ChinaDataAdapter: {source_name} returned no data for {ticker}"
                )
            except Exception as e:
                logger.warning(
                    f"ChinaDataAdapter: {source_name} failed for {ticker}: {e}"
                )
                continue

        logger.warning(
            f"ChinaDataAdapter: all fallbacks exhausted for {ticker}"
        )
        return None

    async def fetch_history_async(
        self,
        ticker: str,
        start: str | date | None = None,
        end: str | date | None = None,
    ) -> Optional[pd.DataFrame]:
        """Async wrapper for fetch_history (runs in thread pool).

        Args:
            ticker: Raw ticker symbol.
            start: Start date.
            end: End date.

        Returns:
            DataFrame or None.
        """
        import asyncio

        return await asyncio.to_thread(
            self.fetch_history, ticker, start, end
        )
