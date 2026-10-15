"""
Market data engine - data-acquisition layer aligned with top quant funds.
Prefers China-reachable sources (efinance + Tencent/Sina APIs);
yfinance is the overseas-network fallback.
"""
import os
import re
import time
from datetime import datetime
from typing import Dict, List, Optional
import pandas as pd
from loguru import logger

from configs.settings import settings
from backend.data_engine.china_adapter import china_data_adapter

# Point the cache at a project-local directory
_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "cache", "yfinance")
os.makedirs(_CACHE_DIR, exist_ok=True)
os.environ.setdefault("YFINANCE_CACHE_DIR", _CACHE_DIR)

# HK numeric-code mapping (strip leading zeros, e.g. 00700 → 0700)
_HK_DIGIT_MAP = {"00700": "0700", "09988": "9988", "03690": "3690", "09999": "9999",
                 "01810": "1810", "00941": "0941", "00883": "0883", "01299": "1299"}

_KNOWN_HK_SUFFIXES = (".HK", ".SI", ".AX", ".NZ")


class MarketDataEngine:
    """
    Market data engine.
    - Multi-market support (US + HK)
    - Unified multi-source interface
    - Automatic trading-calendar handling
    - Cache management
    """

    def __init__(self):
        self.cache: Dict[str, pd.DataFrame] = {}
        self._last_fetch: Dict[str, datetime] = {}
        self._is_market_open = False

    @staticmethod
    def detect_market(ticker: str) -> str:
        """Detect market from a ticker code."""
        if ticker.endswith(".HK"):
            return "HK"
        if ticker.endswith(".SI"):
            return "SG"
        if ticker.endswith(".AX"):
            return "AU"
        if ticker.endswith(".NZ"):
            return "NZ"
        return "US"

    @staticmethod
    def normalize_ticker(ticker: str) -> str:
        """
        P0-1: Auto-complete HK suffixes so yfinance can resolve the symbol.

        Rules:
        1. Pure digits (e.g. 00700, 09988) → strip leading zeros, append .HK; mapping table first
        2. Pure digits without .HK/.SI/.AX/.NZ → append .HK
        3. Already-suffixed tickers are returned as-is

        Examples:
            '00700' → '0700.HK'
            '09988' → '9988.HK'
            'AAPL'  → 'AAPL'
            '0700.HK' → '0700.HK'
            'D05.SI' → 'D05.SI'
        """
        if not ticker or not isinstance(ticker, str):
            return ticker

        ticker = ticker.strip().upper()

        # Already has a known market suffix
        if any(ticker.endswith(suffix) for suffix in _KNOWN_HK_SUFFIXES):
            return ticker

        # Pure numeric ticker — treat as HK stock
        if re.match(r'^\d+$', ticker):
            # Check the mapping table first
            if ticker in _HK_DIGIT_MAP:
                mapped = _HK_DIGIT_MAP[ticker]
            else:
                # Strip leading zeros (e.g., 00700 → 0700)
                mapped = ticker.lstrip('0') or '0'
                if len(mapped) < 4:
                    mapped = mapped.zfill(4)
            return f"{mapped}.HK"

        return ticker

    @staticmethod
    def get_yfinance_symbol(ticker: str) -> str:
        """
        P0-1: Convert to a yfinance-resolvable symbol.
        Auto-complete .HK via normalize_ticker.
        """
        return MarketDataEngine.normalize_ticker(ticker)

    @staticmethod
    def get_display_symbol(ticker: str) -> str:
        """Return a display-friendly code."""
        return ticker.replace(".HK", "")

    # ================================================================
    # Public API
    # ================================================================

    def get_historical_data(
        self,
        ticker: str,
        period: str = "2y",
        interval: str = "1d",
        force_refresh: bool = False
    ) -> pd.DataFrame:
        """
        Fetch historical OHLCV bars.
        Prefers China-reachable sources (efinance + Tencent API); yfinance is fallback.

        Args:
            ticker: symbol (US: AAPL, HK: 0700.HK or 00700)
            period: 1d/5d/1mo/3mo/6mo/1y/2y/5y/10y/ytd/max
            interval: 1m/2m/5m/15m/30m/60m/1d/5d/1wk/1mo/3mo
            force_refresh: bypass cache

        Returns:
            DataFrame with columns: open, high, low, close, volume, ...
        """
        # P0-1: auto-normalize ticker
        yf_ticker = self.normalize_ticker(ticker)
        cache_key = f"{yf_ticker}_{period}_{interval}"
        market = self.detect_market(yf_ticker)
        display = self.get_display_symbol(yf_ticker)

        # Cache hit (valid for 5 minutes)
        if not force_refresh and cache_key in self.cache:
            last_fetch = self._last_fetch.get(cache_key)
            if last_fetch and (datetime.now() - last_fetch).seconds < 300:
                return self.cache[cache_key]

        try:
            logger.info(f"📥 [{market}] {display} fetching history: period={period}, interval={interval}")

            # Prefer China-reachable sources
            df = china_data_adapter.get_historical_data(yf_ticker, period, interval, force_refresh)

            if df.empty:
                logger.warning(f"⚠️ [{market}] {display} China data source returned no data (ticker={yf_ticker})")
                return pd.DataFrame()

            # Normalize column names across sources
            col_map = {"Open": "open", "High": "high", "Low": "low",
                       "Close": "close", "Volume": "volume",
                       "Dividends": "dividends", "Stock Splits": "stock_splits"}
            for old, new in col_map.items():
                if old in df.columns:
                    df = df.rename(columns={old: new})

            # Add identity columns if missing
            if "ticker" not in df.columns:
                df["ticker"] = yf_ticker
            if "market" not in df.columns:
                df["market"] = market
            if df.index.name is None or df.index.name == "":
                df.index.name = "timestamp"

            # Update cache
            self.cache[cache_key] = df
            self._last_fetch[cache_key] = datetime.now()

            currency = "USD" if market == "US" else "HKD"
            logger.info(f"✅ [{market}] {display} fetch complete: {len(df)} rows, {currency}")
            return df

        except Exception as e:
            logger.error(f"❌ Failed to fetch {yf_ticker} data: {e}")
            return pd.DataFrame()

    def get_multi_ticker_data(
        self,
        tickers: Optional[List[str]] = None,
        period: str = "2y",
        interval: str = "1d"
    ) -> Dict[str, pd.DataFrame]:
        """
        Batch-fetch data for multiple tickers (US/HK auto-detected).

        Returns:
            {ticker: DataFrame}
        """
        if tickers is None:
            tickers = settings.DATA_ALL_TICKERS
        result = {}
        for ticker in tickers:
            df = self.get_historical_data(ticker, period, interval)
            if not df.empty:
                result[ticker] = df
            time.sleep(0.5)
        return result

    def get_realtime_quote(self, ticker: str) -> Optional[Dict]:
        """
        Fetch a realtime quote.
        Prefers China-reachable APIs (Tencent/Sina); yfinance is fallback.
        """
        yf_ticker = self.normalize_ticker(ticker)
        market = self.detect_market(yf_ticker)
        display = self.get_display_symbol(yf_ticker)

        try:
            quote = china_data_adapter.get_realtime_quote(yf_ticker)
            if quote:
                quote["display"] = display
                return quote
            return None
        except Exception as e:
            logger.error(f"❌ [{market}] {display} realtime quote failed: {e}")
            return None

    def get_market_status(self) -> Dict:
        """Return status for all markets."""
        import pytz
        # MARKET_CONFIGS is a module-level setting
        from configs.settings import settings
        market_configs = settings.market_configs_dict

        now_utc = datetime.now(pytz.UTC)
        markets = {}

        for name, mc in market_configs.items():
            try:
                tz = pytz.timezone(mc["timezone"])
                local = now_utc.astimezone(tz)
                is_weekday = local.weekday() < 5
                open_h, open_m = map(int, mc["open"].split(":"))
                close_h, close_m = map(int, mc["close"].split(":"))
                current_minutes = local.hour * 60 + local.minute
                open_minutes = open_h * 60 + open_m
                close_minutes = close_h * 60 + close_m
                is_open = is_weekday and open_minutes <= current_minutes <= close_minutes

                markets[name] = {
                    "is_open": is_open,
                    "local_time": local.strftime("%H:%M:%S"),
                    "local_date": local.strftime("%Y-%m-%d"),
                    "timezone": mc["timezone"],
                    "currency": mc["currency"],
                    "trading_hours": f"{mc['open']}-{mc['close']}",
                }
            except Exception:
                markets[name] = {"is_open": False, "timezone": mc["timezone"], "error": True}

        return {
            "markets": markets,
            "timestamp": now_utc.isoformat(),
            "any_open": any(m.get("is_open", False) for m in markets.values()),
        }

    # ================================================================
    # Tiger Brokers adapter (reserved)
    # ================================================================

    def _tiger_get_historical(self, ticker: str, **kwargs) -> pd.DataFrame:
        """
        Tiger Brokers historical-data interface (reserved).
        Replace yfinance once an API account is available.
        """
        # from tiger_open_python_sdk import TigerApiClient
        # client = TigerApiClient(...)
        # ...
        raise NotImplementedError("Tiger Brokers SDK not yet integrated")

    def _tiger_get_realtime(self, ticker: str) -> Dict:
        """Tiger Brokers realtime quote interface (reserved)."""
        raise NotImplementedError("Tiger Brokers SDK not yet integrated")


# Global singleton
market_data_engine = MarketDataEngine()
