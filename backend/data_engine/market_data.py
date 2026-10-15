"""
Market data engine.
US history comes from Tiger quotes, then yfinance, then the China feed.
Other markets try the China feed first.
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
        US names try Tiger quotes, then yfinance, then the China feed.
        Other markets try the China feed first.

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

            # US names on an overseas host fail the China feed. Try the broker
            # and yfinance before spending a request on East Money.
            if market == "US":
                loaders = (
                    ("tiger", lambda: self._history_from_tiger(yf_ticker, period)),
                    ("yfinance", lambda: self._history_from_yfinance(yf_ticker, period, interval)),
                    ("china", lambda: china_data_adapter.get_historical_data(yf_ticker, period, interval, force_refresh)),
                )
            else:
                loaders = (
                    ("china", lambda: china_data_adapter.get_historical_data(yf_ticker, period, interval, force_refresh)),
                    ("yfinance", lambda: self._history_from_yfinance(yf_ticker, period, interval)),
                    ("tiger", lambda: self._history_from_tiger(yf_ticker, period)),
                )

            df = pd.DataFrame()
            source = ""
            for name, loader in loaders:
                try:
                    candidate = loader()
                except Exception as exc:
                    logger.debug(f"{name} history failed for {yf_ticker}: {exc}")
                    candidate = pd.DataFrame()
                if candidate is not None and not getattr(candidate, "empty", True):
                    df = candidate
                    source = name
                    break

            if df.empty:
                logger.warning(f"⚠️ [{market}] {display} no bars from tiger, yfinance, or China feed")
                return pd.DataFrame()
            logger.info(f"📥 [{market}] {display} bars from {source}: {len(df)} rows")

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

    def warm_history(
        self,
        tickers: List[str],
        period: str = "2y",
        interval: str = "1d",
    ) -> int:
        """Fill the short-lived cache for US names before a cycle walks them.

        One Tiger ``get_bars`` call covers a batch. Names still missing are
        loaded with a single yfinance download. Returns how many symbols
        were cached.
        """
        pending: List[str] = []
        for ticker in tickers:
            yf_ticker = self.normalize_ticker(ticker)
            if self.detect_market(yf_ticker) != "US":
                continue
            cache_key = f"{yf_ticker}_{period}_{interval}"
            cached = self.cache.get(cache_key)
            if cached is not None and not getattr(cached, "empty", True):
                continue
            pending.append(yf_ticker)
        if not pending:
            return 0

        filled = self._warm_from_tiger_batch(pending, period, interval)
        missing = [
            ticker for ticker in pending
            if self.cache.get(f"{ticker}_{period}_{interval}") is None
            or getattr(self.cache.get(f"{ticker}_{period}_{interval}"), "empty", True)
        ]
        filled += self._warm_from_yfinance_batch(missing, period, interval)
        logger.info(f"warm_history cached {filled}/{len(pending)} US names")
        return filled

    @staticmethod
    def _history_bar_limit(period: str) -> int:
        limits = {
            "5d": 10, "1mo": 30, "3mo": 70, "6mo": 140,
            "1y": 260, "2y": 520, "5y": 1200, "10y": 2500, "max": 2500,
        }
        return limits.get(period, 520)

    @staticmethod
    def _tiger_error_is_fatal(exc: Exception) -> bool:
        msg = str(exc).lower()
        needles = (
            "token", "permission", "unauthorized", "private key",
            "not configured", "forbidden", "invalid key", "quote permission",
        )
        return any(needle in msg for needle in needles)

    def _ensure_tiger_quote(self):
        """Return a cached QuoteClient. A connect failure disables Tiger bars."""
        if getattr(self, "_tiger_quote_failed", False):
            return None
        quote = getattr(self, "_tiger_quote", None)
        if quote is not None:
            return quote
        try:
            from shared.tiger_sdk import connect

            _trade, quote = connect()
        except Exception as exc:
            logger.info(f"Tiger quote connect failed: {exc}")
            self._tiger_quote_failed = True
            self._tiger_quote = None
            return None
        if quote is None:
            self._tiger_quote_failed = True
            return None
        self._tiger_quote = quote
        return quote

    def _store_history_cache(
        self,
        ticker: str,
        period: str,
        interval: str,
        df: pd.DataFrame,
        source: str,
    ) -> None:
        cache_key = f"{ticker}_{period}_{interval}"
        self.cache[cache_key] = df
        self._last_fetch[cache_key] = datetime.now()
        logger.info(f"📥 [{self.detect_market(ticker)}] {ticker} bars from {source}: {len(df)} rows")

    def _normalize_ohlcv(self, df: pd.DataFrame, ticker: str) -> pd.DataFrame:
        """Lowercase OHLCV with a timezone-naive DatetimeIndex."""
        if df is None or getattr(df, "empty", True):
            return pd.DataFrame()
        work = self._coerce_bar_index(df)
        if work.empty or not isinstance(work.index, pd.DatetimeIndex):
            return pd.DataFrame()
        rename = {
            "open": "open", "high": "high", "low": "low",
            "close": "close", "volume": "volume",
            "adj_close": "adj_close",
        }
        keep = [col for col in rename if col in work.columns]
        if "close" not in keep:
            return pd.DataFrame()
        work = work[keep].apply(pd.to_numeric, errors="coerce")
        work = work.dropna(subset=["close"])
        if work.empty:
            return pd.DataFrame()
        work.index.name = "timestamp"
        work["ticker"] = ticker
        work["market"] = self.detect_market(ticker)
        return work

    @staticmethod
    def _coerce_bar_index(df: pd.DataFrame) -> pd.DataFrame:
        work = df.copy()
        work.columns = [str(col).lower().replace(" ", "_") for col in work.columns]
        if isinstance(work.columns, pd.MultiIndex):
            work.columns = [
                "_".join(str(part).lower() for part in col if part not in ("", None))
                for col in work.columns
            ]
        if "time" in work.columns and not isinstance(work.index, pd.DatetimeIndex):
            raw = work["time"]
            if pd.api.types.is_numeric_dtype(raw):
                parsed = pd.to_datetime(raw, unit="ms", errors="coerce")
                if parsed.isna().all():
                    parsed = pd.to_datetime(raw, errors="coerce")
            else:
                parsed = pd.to_datetime(raw, errors="coerce")
            work = work.drop(columns=["time"])
            work.index = parsed
        if not isinstance(work.index, pd.DatetimeIndex):
            if pd.api.types.is_numeric_dtype(work.index):
                parsed = pd.to_datetime(work.index, unit="ms", errors="coerce")
                if parsed.isna().all():
                    parsed = pd.to_datetime(work.index, errors="coerce")
                work.index = parsed
            else:
                work.index = pd.to_datetime(work.index, errors="coerce")
        work = work[~work.index.isna()]
        if isinstance(work.index, pd.DatetimeIndex) and work.index.tz is not None:
            work.index = work.index.tz_localize(None)
        work.index.name = "timestamp"
        return work

    def _split_tiger_bars(self, bars, tickers: List[str]) -> Dict[str, pd.DataFrame]:
        if bars is None or getattr(bars, "empty", True):
            return {}
        df = bars.copy()
        df.columns = [str(col).lower() for col in df.columns]
        symbol_col = next((col for col in ("symbol", "ticker") if col in df.columns), None)
        frames: Dict[str, pd.DataFrame] = {}
        if symbol_col:
            for symbol, part in df.groupby(symbol_col):
                key = str(symbol).upper()
                frame = self._normalize_ohlcv(part.drop(columns=[symbol_col]), key)
                if not frame.empty:
                    frames[key] = frame
            return frames
        if len(tickers) == 1:
            key = tickers[0].upper()
            frame = self._normalize_ohlcv(df, key)
            if not frame.empty:
                frames[key] = frame
        return frames

    def _warm_from_tiger_batch(self, tickers: List[str], period: str, interval: str) -> int:
        quote = self._ensure_tiger_quote()
        if quote is None or not tickers:
            return 0
        limit = self._history_bar_limit(period)
        filled = 0
        for start in range(0, len(tickers), 20):
            batch = tickers[start:start + 20]
            try:
                bars = quote.get_bars(symbols=batch, period="day", limit=limit)
            except Exception as exc:
                logger.info(f"Tiger batch bars failed ({len(batch)} names): {exc}")
                if self._tiger_error_is_fatal(exc):
                    self._tiger_quote_failed = True
                    self._tiger_quote = None
                    break
                continue
            for ticker, frame in self._split_tiger_bars(bars, batch).items():
                self._store_history_cache(ticker, period, interval, frame, "tiger")
                filled += 1
        return filled

    def _warm_from_yfinance_batch(self, tickers: List[str], period: str, interval: str) -> int:
        if not tickers:
            return 0
        try:
            import yfinance as yf

            raw = yf.download(
                tickers=tickers,
                period=period,
                interval=interval,
                group_by="ticker",
                threads=True,
                progress=False,
                auto_adjust=False,
            )
        except Exception as exc:
            logger.info(f"yfinance batch failed: {exc}")
            return 0
        if raw is None or getattr(raw, "empty", True):
            return 0
        filled = 0
        for ticker in tickers:
            part = self._slice_download(raw, ticker)
            frame = self._normalize_ohlcv(part, ticker)
            if frame.empty:
                continue
            self._store_history_cache(ticker, period, interval, frame, "yfinance")
            filled += 1
        return filled

    @staticmethod
    def _slice_download(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
        if not isinstance(raw.columns, pd.MultiIndex):
            return raw
        wanted = ticker.upper()
        for level in (0, 1):
            for value in raw.columns.get_level_values(level):
                if str(value).upper() != wanted:
                    continue
                if level == 0:
                    return raw[value]
                return raw.xs(value, axis=1, level=1)
        return pd.DataFrame()

    def _history_from_yfinance(self, ticker: str, period: str, interval: str) -> pd.DataFrame:
        from backend.data_engine.china_adapter import get_history_yfinance

        frame = get_history_yfinance(ticker, period=period, interval=interval)
        return self._normalize_ohlcv(frame, ticker)

    def _history_from_tiger(self, ticker: str, period: str) -> pd.DataFrame:
        """Daily bars from the Tiger quote client. Empty when the SDK is down.

        A bad symbol does not disable quotes for the rest of the universe.
        Only a failed connection, or an auth/permission error, does that.
        """
        quote = self._ensure_tiger_quote()
        if quote is None:
            return pd.DataFrame()
        try:
            bars = quote.get_bars(
                symbols=[ticker],
                period="day",
                limit=self._history_bar_limit(period),
            )
        except Exception as exc:
            logger.info(f"Tiger bars unavailable for {ticker}: {exc}")
            if self._tiger_error_is_fatal(exc):
                self._tiger_quote_failed = True
                self._tiger_quote = None
            return pd.DataFrame()
        frames = self._split_tiger_bars(bars, [ticker])
        return frames.get(ticker.upper(), pd.DataFrame())

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
