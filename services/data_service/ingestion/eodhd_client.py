"""services/data_service/ingestion/eodhd_client.py – EODHD API backup data source.

P1 priority — skeleton implemented with graceful degradation.
Activates when yfinance fails or is rate-limited.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from loguru import logger

from shared.core.exceptions import DataFetchError


class EODHDClient:
    """EOD Historical Data API client (backup data source).

    Activated as fallback when primary sources fail.
    Full implementation pending P1 API key provisioning.
    """

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key
        self._base_url = "https://eodhistoricaldata.com/api"

    @property
    def is_available(self) -> bool:
        """Check if the EODHD client is configured and available."""
        return bool(self._api_key)

    async def fetch_daily(
        self,
        ticker: str,
        start: date | None = None,
        end: date | None = None,
    ) -> Optional[pd.DataFrame]:
        """Fetch daily OHLCV data from EODHD.

        Args:
            ticker: Stock ticker in EODHD format (e.g. 'AAPL.US', '700.HK').
            start: Start date.
            end: End date.

        Returns:
            DataFrame with OHLCV data, or None if unavailable.
        """
        if not self.is_available:
            logger.debug(f"EODHD client not configured — skipping {ticker}")
            return None

        start = start or date.today() - timedelta(days=365)
        end = end or date.today()
        url = (
            f"{self._base_url}/eod/{ticker}"
            f"?api_token={self._api_key}"
            f"&from={start.isoformat()}&to={end.isoformat()}"
            f"&fmt=json"
        )

        try:
            import httpx

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()

            if not data:
                return None

            df = pd.DataFrame(data)
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
            df = df.rename(columns={
                "open": "open", "high": "high", "low": "low",
                "close": "close", "adjusted_close": "adj_close",
                "volume": "volume",
            })
            logger.info(f"EODHD: fetched {len(df)} bars for {ticker}")
            return df

        except ImportError:
            logger.debug("httpx not available for EODHD")
            return None
        except Exception as e:
            logger.warning(f"EODHD fetch failed for {ticker}: {e}")
            return None

    async def fetch_fundamentals(self, ticker: str) -> dict:
        """Fetch fundamental data from EODHD.

        Args:
            ticker: Stock ticker.

        Returns:
            Dictionary of fundamental data.
        """
        if not self.is_available:
            return {}

        url = (
            f"{self._base_url}/fundamentals/{ticker}"
            f"?api_token={self._api_key}"
        )

        try:
            import httpx

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.warning(f"EODHD fundamentals failed for {ticker}: {e}")
            return {}
