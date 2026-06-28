"""services/data_service/ingestion/tencent_client.py – 腾讯行情客户端.

Fetches historical and daily K-line data from Tencent Finance's
public market data APIs. Used as a fallback for A-share data.

Primary: https://web.ifzq.gtimg.cn/appstock/app/fqkline/get
Fallback: http://qt.gtimg.cn/q=<code> for real-time quotes
"""

from __future__ import annotations

import asyncio
import re
from datetime import date
from typing import Optional

import pandas as pd
import requests
from loguru import logger


class TencentClient:
    """腾讯 (Tencent) Finance market data client.

    Fetches K-line data for A-share (and HK) tickers. Handles
    SH/SZ prefix logic and returns standardized OHLCV DataFrames.
    """

    KLINE_URL: str = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    QT_URL: str = "http://qt.gtimg.cn/q="

    def __init__(self, timeout: int = 15) -> None:
        self._timeout = timeout
        self._session: Optional[requests.Session] = None

    @property
    def session(self) -> requests.Session:
        """Lazy session with browser-like headers."""
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Referer": "https://gu.qq.com/",
            })
        return self._session

    def _to_tencent_code(self, ticker: str) -> str:
        """Convert ticker to Tencent's code format.

        Args:
            ticker: Raw ticker (e.g. '000001', '000001.SZ', '600519.SH').

        Returns:
            Tencent code (e.g. 'sz000001', 'sh600519').

        Raises:
            ValueError: If the market cannot be determined.
        """
        clean = ticker.upper().strip()

        # Handle explicit suffix
        if ".SZ" in clean:
            return f"sz{clean.replace('.SZ', '')}"
        if ".SH" in clean:
            return f"sh{clean.replace('.SH', '')}"
        if ".HK" in clean:
            return f"hk{clean.replace('.HK', '')}"

        # Heuristic: 6-digit numeric → determine market
        if clean.isdigit() and len(clean) == 6:
            prefix = clean[:2]
            # SH prefixes: 60, 68, 900, 51, 56, 58, 110+
            if prefix in ("60", "68", "51", "56", "58") or prefix.startswith("9"):
                return f"sh{clean}"
            # 11x bonds go to SH as well
            if prefix in ("11",):
                return f"sh{clean}"
            return f"sz{clean}"

        raise ValueError(f"Cannot convert ticker '{ticker}' to Tencent code")

    def fetch_history(
        self,
        ticker: str,
        start: str | date | None = None,
        end: str | date | None = None,
        period: str = "day",
        fqtype: str = "qfq",
    ) -> Optional[pd.DataFrame]:
        """Fetch historical K-line data from Tencent Finance.

        Args:
            ticker: Stock ticker (e.g. '000001', '000001.SZ', '600519.SH').
            start: Start date filter.
            end: End date filter.
            period: K-line period: 'day', 'week', 'month'.
            fqtype: Adjustment type: 'qfq' (forward), 'hfq' (backward), '' (none).

        Returns:
            DataFrame with [open, close, high, low, volume] columns and date index,
            or None if data unavailable.
        """
        try:
            code = self._to_tencent_code(ticker)
        except ValueError as e:
            logger.warning(f"Tencent code conversion failed for {ticker}: {e}")
            return None

        klt = _period_map(period)
        params: dict = {
            "_var": "kline_" + period,
            "param": f"{code},{period},,,320,{fqtype}",
        }

        try:
            resp = self.session.get(
                self.KLINE_URL, params=params, timeout=self._timeout
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Tencent kline request failed for {ticker}: {e}")
            return self._fetch_qt_fallback(ticker, start, end)

        try:
            data = resp.json()
        except ValueError:
            logger.warning(f"Tencent returned non-JSON response for {ticker}")
            return self._fetch_qt_fallback(ticker, start, end)

        # Navigate JSON structure
        stock_data = data.get("data", {}).get(code)
        if stock_data is None:
            logger.warning(f"Tencent: no data for code {code}")
            return self._fetch_qt_fallback(ticker, start, end)

        # Choose adjusted or unadjusted list
        kline_key = f"qfq{period}" if fqtype == "qfq" else f"{fqtype}{period}" if fqtype else period
        if kline_key not in stock_data:
            # Try fallback keys
            for key in stock_data:
                if "day" in key or "week" in key or "month" in key:
                    kline_key = key
                    break

        rows_raw = stock_data.get(kline_key, [])
        if not rows_raw:
            return self._fetch_qt_fallback(ticker, start, end)

        # Parse rows: [date_str, open, close, high, low, volume, ...]
        rows: list[dict] = []
        for item in rows_raw:
            if not isinstance(item, list) or len(item) < 6:
                continue
            try:
                date_str = str(item[0])
                rows.append({
                    "date": pd.Timestamp(date_str),
                    "open": float(item[1]),
                    "close": float(item[2]),
                    "high": float(item[3]),
                    "low": float(item[4]),
                    "volume": float(item[5]),
                })
            except (ValueError, IndexError):
                continue

        if not rows:
            return None

        df = pd.DataFrame(rows)
        df = df.set_index("date").sort_index()

        # Filter by date range
        if start is not None:
            df = df[df.index >= pd.Timestamp(start)]
        if end is not None:
            df = df[df.index <= pd.Timestamp(end)]

        logger.info(f"Tencent: fetched {len(df)} bars for {ticker} (code={code})")
        return df if not df.empty else None

    def _fetch_qt_fallback(
        self,
        ticker: str,
        start: str | date | None = None,
        end: str | date | None = None,
    ) -> Optional[pd.DataFrame]:
        """Fallback: parse real-time quote page for daily snapshot.

        Uses qt.gtimg.cn which returns a single-line text response
        with current quote data. Only provides the current day's bar
        — not full history.
        """
        try:
            code = self._to_tencent_code(ticker)
        except ValueError:
            return None

        try:
            resp = self.session.get(
                self.QT_URL + code, timeout=self._timeout
            )
            resp.raise_for_status()
            text = resp.text
        except requests.RequestException as e:
            logger.error(f"Tencent qt fallback failed for {ticker}: {e}")
            return None

        # Parse qt format: v_<code>="~<field1>~<field2>~..."
        # Typical fields (partial): 1=name, 3=price, 4=prev_close, 5=open,
        #   31=volume, 33=high, 34=low, 43=change_pct
        pattern = rf'v_{re.escape(code)}="(.*?)"'
        match = re.search(pattern, text)
        if not match:
            return None

        fields = match.group(1).split("~")
        if len(fields) < 35:
            return None

        try:
            today = date.today()
            current = float(fields[3]) if fields[3] else 0.0
            open_price = float(fields[5]) if fields[5] else current
            high = float(fields[33]) if fields[33] else current
            low = float(fields[34]) if fields[34] else current
            volume = float(fields[6]) if fields[6] else 0.0

            if current == 0.0:
                return None

            df = pd.DataFrame([{
                "date": pd.Timestamp(today),
                "open": open_price,
                "close": current,
                "high": high,
                "low": low,
                "volume": volume,
            }])
            df = df.set_index("date")

            logger.info(f"Tencent qt fallback: 1 bar for {ticker}")
            return df
        except (ValueError, IndexError) as e:
            logger.warning(f"Tencent qt parse error for {ticker}: {e}")
            return None

    async def fetch_history_async(
        self,
        ticker: str,
        start: str | date | None = None,
        end: str | date | None = None,
    ) -> Optional[pd.DataFrame]:
        """Async wrapper around fetch_history."""
        return await asyncio.to_thread(self.fetch_history, ticker, start, end)


def _period_map(period: str) -> str:
    """Map period to Tencent API parameter."""
    mapping = {"day": "day", "week": "week", "month": "month"}
    return mapping.get(period, "day")
