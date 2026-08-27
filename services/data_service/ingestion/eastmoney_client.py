"""services/data_service/ingestion/eastmoney_client.py – Eastmoney market-data client.

Fetches historical K-line data from Eastmoney's public API.
Supports A-share (SH/SZ) tickers with automatic secid conversion.

API endpoint: https://push2his.eastmoney.com/api/qt/stock/kline/get
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Optional

import pandas as pd
import requests
from loguru import logger


class EastmoneyClient:
    """Eastmoney historical K-line data client.

    Fetches daily OHLCV data for Chinese A-share tickers from the
    public Eastmoney push API. Handles SH/SZ prefix detection.
    """

    BASE_URL: str = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

    # Mapping: numeric prefix → market code
    SH_PREFIXES: frozenset[str] = frozenset(
        {"60", "68", "900", "51", "56", "58", "110", "113", "118", "128"}
    )

    def __init__(self, timeout: int = 15) -> None:
        self._timeout = timeout
        self._session: Optional[requests.Session] = None

    @property
    def session(self) -> requests.Session:
        """Lazy session with headers."""
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Referer": "https://quote.eastmoney.com/",
            })
        return self._session

    def _build_secid(self, ticker: str) -> str:
        """Convert a ticker symbol to Eastmoney secid format.

        Args:
            ticker: Raw ticker (e.g. '000001', '000001.SZ', '600519.SH').

        Returns:
            Eastmoney secid string (e.g. '0.000001' for SZ, '1.600519' for SH).

        Raises:
            ValueError: If the ticker cannot be mapped to a known market.
        """
        # Strip suffix if present
        clean = ticker.upper().replace(".SZ", "").replace(".SH", "").replace(".HK", "").strip()

        if not clean.isdigit() or len(clean) != 6:
            raise ValueError(f"Cannot convert ticker '{ticker}' to Eastmoney secid")

        prefix = clean[:2]
        if prefix in self.SH_PREFIXES:
            return f"1.{clean}"
        # Default to Shenzhen
        return f"0.{clean}"

    def fetch_history(
        self,
        ticker: str,
        start: str | date | None = None,
        end: str | date | None = None,
        period: str = "day",
        fqt: int = 1,
    ) -> Optional[pd.DataFrame]:
        """Fetch historical daily K-line data from Eastmoney.

        Args:
            ticker: Stock ticker (supports 000001, 000001.SZ, 600519.SH).
            start: Start date (ISO string or date object).
            end: End date (ISO string or date object).
            period: K-line period: 'day', 'week', 'month'.
            fqt: Adjustment mode: 0=unadjusted, 1=forward-adjusted, 2=backward-adjusted.

        Returns:
            DataFrame with columns [open, high, low, close, volume] and date index,
            or None if no data is available.
        """
        try:
            secid = self._build_secid(ticker)
        except ValueError as e:
            logger.warning(f"Eastmoney secid conversion failed for {ticker}: {e}")
            return None

        # Build params
        params: dict = {
            "secid": secid,
            "ut": "fa5fd1943c7b386f172d6893dbfb6a6c",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": _klt_map(period),
            "fqt": str(fqt),
            "end": "20500101",
            "lmt": "10000",
        }

        try:
            resp = self.session.get(self.BASE_URL, params=params, timeout=self._timeout)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Eastmoney request failed for {ticker}: {e}")
            return None

        data = resp.json()
        if data is None or data.get("data") is None:
            logger.warning(f"Eastmoney returned no data for {ticker}")
            return None

        klines = data["data"].get("klines")
        if not klines:
            logger.warning(f"Eastmoney returned empty klines for {ticker}")
            return None

        # Parse kline strings: "date,open,close,high,low,volume,amount,amplitude,pct_chg,chg,turnover"
        rows: list[dict] = []
        for line in klines:
            parts = line.split(",")
            if len(parts) < 6:
                continue
            try:
                rows.append({
                    "date": pd.Timestamp(parts[0]),
                    "open": float(parts[1]),
                    "close": float(parts[2]),
                    "high": float(parts[3]),
                    "low": float(parts[4]),
                    "volume": float(parts[5]),
                })
            except (ValueError, IndexError):
                continue

        if not rows:
            return None

        df = pd.DataFrame(rows)
        df = df.set_index("date").sort_index()

        # Apply date range filter
        if start is not None:
            start_ts = pd.Timestamp(start)
            df = df[df.index >= start_ts]
        if end is not None:
            end_ts = pd.Timestamp(end)
            df = df[df.index <= end_ts]

        logger.info(f"Eastmoney: fetched {len(df)} bars for {ticker} (secid={secid})")
        return df if not df.empty else None

    async def fetch_history_async(
        self,
        ticker: str,
        start: str | date | None = None,
        end: str | date | None = None,
    ) -> Optional[pd.DataFrame]:
        """Async wrapper around fetch_history."""
        return await asyncio.to_thread(self.fetch_history, ticker, start, end)


def _klt_map(period: str) -> str:
    """Map period string to Eastmoney klt parameter."""
    mapping = {"day": "101", "week": "102", "month": "103"}
    return mapping.get(period, "101")
