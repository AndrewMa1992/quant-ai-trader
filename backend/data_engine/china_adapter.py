"""
China-network data adapter — yfinance replacement.
Prefers APIs reachable from mainland China:
  - efinance / East Money direct API for US historical bars (requires mainland access)
  - Tencent Finance API (qt.gtimg.cn) for HK history + cross-market realtime quotes
  - Sina Finance API (hq.sinajs.cn) as a realtime fallback
  - yfinance as the overseas-network last resort

None of the China-reachable APIs depend on Google/Yahoo (often blocked).
Sources auto-failover by priority to fit different network environments.
"""

import json
import re
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd
import requests
from loguru import logger


# ============================================================
# East Money direct API (more controllable than efinance)
# ============================================================
_EASTMONEY_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
_EASTMONEY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Referer": "https://quote.eastmoney.com/",
}

# Tencent Finance API
_TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
_TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="


def _eastmoney_secid(ticker: str) -> str:
    """Convert to East Money secid format: market.code — HK is 5 digits."""
    if ticker.endswith(".HK"):
        code = ticker.replace(".HK", "").zfill(5)
        return f"116.{code}"  # HK
    if ticker.endswith(".SI"):
        code = ticker.replace(".SI", "")
        return f"122.{code}"  # Singapore
    # US: 105=Nasdaq, 106=NYSE
    return f"105.{ticker}"


def _tencent_kline_code(ticker: str) -> str:
    """Convert to Tencent KLine API code — HK must be 5 digits."""
    if ticker.endswith(".HK"):
        code = ticker.replace(".HK", "")
        # HK codes must be 5 digits, left-padded: 0700 → 00700
        code = code.zfill(5)
        return f"hk{code}"
    if ticker.endswith(".SI"):
        code = ticker.replace(".SI", "")
        return f"sg{code}"
    if ticker.endswith(".AX"):
        code = ticker.replace(".AX", "")
        return f"au{code}"
    if ticker.endswith(".NZ"):
        code = ticker.replace(".NZ", "")
        return f"nz{code}"
    return f"us{ticker}"


def _tencent_quote_code(ticker: str) -> str:
    """Convert to Tencent realtime quote code — HK is 5 digits."""
    if ticker.endswith(".HK"):
        code = ticker.replace(".HK", "").zfill(5)
        return f"r_hk{code}"
    if ticker.endswith(".SI"):
        code = ticker.replace(".SI", "")
        return f"r_sg{code}"
    if ticker.endswith(".AX"):
        code = ticker.replace(".AX", "")
        return f"r_au{code}"
    if ticker.endswith(".NZ"):
        code = ticker.replace(".NZ", "")
        return f"r_nz{code}"
    return f"us{ticker}"


# ============================================================
# Historical data — East Money direct
# ============================================================

def get_history_eastmoney(
    ticker: str,
    period: str = "2y",
    interval: str = "1d",
) -> pd.DataFrame:
    """
    Fetch historical bars via the East Money API (US + HK).
    Requires mainland China access or East Money API permission.
    """
    secid = _eastmoney_secid(ticker)
    market = "HK" if ticker.endswith(".HK") else "US"

    # period → bar count
    period_map = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "5y": 1250, "10y": 2500}
    count = period_map.get(period, 730)

    # interval → klt
    klt_map = {"1d": 101, "1wk": 102, "1mo": 103}
    klt = klt_map.get(interval, 101)

    # Date range
    end_date = datetime.now().strftime("%Y%m%d")
    days = period_map.get(period, 730)
    beg_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

    params = {
        "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "beg": beg_date,
        "end": end_date,
        "rtntype": 6,
        "secid": secid,
        "klt": klt,
        "fqt": 1,  # forward-adjusted
    }

    try:
        resp = requests.get(
            _EASTMONEY_KLINE_URL, params=params,
            headers=_EASTMONEY_HEADERS, timeout=15, verify=False,
        )
        resp.raise_for_status()
        data = resp.json()

        klines = data.get("data", {}).get("klines", [])
        if not klines:
            return pd.DataFrame()

        rows = []
        for line in klines:
            parts = line.split(",")
            if len(parts) >= 6:
                rows.append({
                    "timestamp": parts[0],
                    "open": float(parts[1]),
                    "close": float(parts[2]),
                    "high": float(parts[3]),
                    "low": float(parts[4]),
                    "volume": float(parts[5]),
                })

        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp")
        df["ticker"] = ticker
        df["market"] = market

        logger.info(f"✅ [East Money] {ticker} fetch complete: {len(df)} rows")
        return df

    except Exception as e:
        logger.debug(f"East Money API {ticker} failed: {e}")
        return pd.DataFrame()


# ============================================================
# Historical data — Tencent Finance
# ============================================================

def get_history_tencent(
    ticker: str,
    period: str = "2y",
    interval: str = "1d",
) -> pd.DataFrame:
    """
    Fetch historical bars via the Tencent Finance API.
    Strong for HK (full history); US typically has only a few points.
    """
    code = _tencent_kline_code(ticker)
    market = "HK" if ticker.endswith(".HK") else "US"

    period_map = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 500, "5y": 1250}
    count = period_map.get(period, 500)
    klt_map = {"1d": "day", "1wk": "week", "1mo": "month"}
    klt = klt_map.get(interval, "day")

    start_date = ""
    if period in ("1mo", "3mo", "6mo"):
        days = period_map.get(period, 365)
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    url = f"{_TENCENT_KLINE_URL}?param={code},{klt},{start_date},,{count},qfq"

    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = json.loads(resp.text)

        stock_key = list(data.get("data", {}).keys())[0] if data.get("data") else None
        if not stock_key:
            return pd.DataFrame()

        kline_data = data["data"][stock_key].get("qfqday") or data["data"][stock_key].get("day") or []
        if not kline_data or len(kline_data) < 3:
            return pd.DataFrame()  # Tencent US often returns 1-2 points; skip

        # Tencent rows may have 7 columns (7th is a dividend dict); keep the first 6
        rows = []
        for row in kline_data:
            if len(row) >= 6:
                rows.append(row[:6])

        df = pd.DataFrame(rows, columns=["date", "open", "close", "high", "low", "volume"])
        df["date"] = pd.to_datetime(df["date"])
        for col in ["open", "close", "high", "low", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.rename(columns={"date": "timestamp"})
        df = df.set_index("timestamp")
        df["ticker"] = ticker
        df["market"] = market

        logger.info(f"✅ [Tencent] {ticker} fetch complete: {len(df)} rows")
        return df

    except Exception as e:
        logger.debug(f"Tencent API {ticker} failed: {e}")
        return pd.DataFrame()


# ============================================================
# Historical data — efinance
# ============================================================

def get_history_efinance(
    ticker: str,
    period: str = "2y",
    interval: str = "1d",
) -> pd.DataFrame:
    """Fetch history via efinance (strong for US; HK is unstable)."""
    import efinance as ef

    market = "HK" if ticker.endswith(".HK") else "US"
    period_days = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "5y": 1825}
    days = period_days.get(period, 730)
    start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    end = datetime.now().strftime("%Y%m%d")

    try:
        df = ef.stock.get_quote_history(ticker, beg=start, end=end)
        if df is None or df.empty:
            return pd.DataFrame()

        # efinance returns Chinese OHLCV column names; map via unicode escapes
        df = df.rename(columns={
            "\u65e5\u671f": "timestamp",
            "\u5f00\u76d8": "open",
            "\u6536\u76d8": "close",
            "\u6700\u9ad8": "high",
            "\u6700\u4f4e": "low",
            "\u6210\u4ea4\u91cf": "volume",
        })

        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp")
        for col in ["open", "close", "high", "low", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
        df = df[keep]
        df["ticker"] = ticker
        df["market"] = market

        logger.info(f"✅ [efinance] {ticker} fetch complete: {len(df)} rows")
        return df

    except Exception as e:
        logger.debug(f"efinance {ticker} failed: {e}")
        return pd.DataFrame()


# ============================================================
# Historical data — yfinance (overseas fallback)
# ============================================================

def get_history_yfinance(
    ticker: str,
    period: str = "2y",
    interval: str = "1d",
) -> pd.DataFrame:
    """yfinance last resort (overseas networks only)."""
    try:
        import yfinance as yf
        market = "HK" if ticker.endswith(".HK") else "US"

        stock = yf.Ticker(ticker)
        raw = stock.history(period=period, interval=interval)
        if raw.empty:
            return pd.DataFrame()

        raw = raw.rename(columns={
            "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "volume",
        })
        for col in ["open", "high", "low", "close", "volume"]:
            if col in raw.columns:
                raw[col] = pd.to_numeric(raw[col], errors="coerce")

        keep = [c for c in ["open", "high", "low", "close", "volume"] if c in raw.columns]
        raw = raw[keep]
        raw["ticker"] = ticker
        raw["market"] = market
        raw.index.name = "timestamp"

        logger.info(f"✅ [yfinance] {ticker} fetch complete: {len(raw)} rows")
        return raw

    except Exception as e:
        logger.debug(f"yfinance {ticker} failed: {e}")
        return pd.DataFrame()


# ============================================================
# Realtime quotes — Tencent Finance
# ============================================================

def get_realtime_quote_tencent(ticker: str) -> Optional[Dict]:
    """Fetch a realtime quote via the Tencent Finance API."""
    code = _tencent_quote_code(ticker)
    market = "HK" if ticker.endswith(".HK") else "US"

    try:
        url = f"{_TENCENT_QUOTE_URL}{code}"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        text = resp.text.strip()

        if not text or '~' not in text:
            return None

        parts = text.split("~")
        if len(parts) < 11:
            return None

        name = parts[1] if len(parts) > 1 else ticker
        price = float(parts[3]) if len(parts) > 3 and parts[3] else 0
        prev_close = float(parts[4]) if len(parts) > 4 and parts[4] else 0
        open_price = float(parts[5]) if len(parts) > 5 and parts[5] else 0
        volume = float(parts[6]) if len(parts) > 6 and parts[6] else 0
        high = float(parts[9]) if len(parts) > 9 and parts[9] else 0
        low = float(parts[10]) if len(parts) > 10 and parts[10] else 0

        change = price - prev_close if prev_close else 0
        change_pct = (change / prev_close * 100) if prev_close else 0

        return {
            "ticker": ticker, "name": name, "market": market,
            "price": round(price, 3), "prev_close": round(prev_close, 3),
            "open": round(open_price, 3), "high": round(high, 3), "low": round(low, 3),
            "change": round(change, 3), "change_pct": round(change_pct, 3),
            "volume": int(volume),
            "currency": "HKD" if market == "HK" else "USD",
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.debug(f"Tencent quote {ticker} failed: {e}")
        return None


# ============================================================
# Realtime quotes — Sina Finance
# ============================================================

def get_realtime_quote_sina(ticker: str) -> Optional[Dict]:
    """Fetch a realtime quote via the Sina Finance API."""
    market = "HK" if ticker.endswith(".HK") else "US"

    try:
        if market == "HK":
            code = ticker.replace(".HK", "")
            url = f"https://hq.sinajs.cn/list=rt_hk{code}"
        else:
            url = f"https://hq.sinajs.cn/list=gb_{ticker.lower()}"

        resp = requests.get(url, headers={"Referer": "https://finance.sina.com.cn"}, timeout=10)
        resp.raise_for_status()
        content = resp.text

        match = re.search(r'"([^"]+)"', content)
        if not match:
            return None

        fields = match.group(1).split(",")

        if market == "US" and len(fields) >= 10:
            name = fields[0]
            price = float(fields[1]) if fields[1] else 0
            change_pct = float(fields[2]) if fields[2] else 0
            high = float(fields[6]) if fields[6] else 0
            low = float(fields[7]) if fields[7] else 0
            volume = int(float(fields[10])) if len(fields) > 10 and fields[10] else 0

            return {
                "ticker": ticker, "name": name, "market": "US",
                "price": round(price, 3), "change_pct": round(change_pct, 3),
                "high": round(high, 3), "low": round(low, 3),
                "volume": volume, "currency": "USD",
                "timestamp": datetime.now().isoformat(),
            }

        elif market == "HK" and len(fields) >= 10:
            name = fields[0]
            price = float(fields[6]) if fields[6] else 0
            prev_close = float(fields[3]) if fields[3] else 0
            high = float(fields[4]) if fields[4] else 0
            low = float(fields[5]) if fields[5] else 0
            change = price - prev_close if prev_close else 0
            change_pct = (change / prev_close * 100) if prev_close else 0

            return {
                "ticker": ticker, "name": name, "market": "HK",
                "price": round(price, 3), "prev_close": round(prev_close, 3),
                "high": round(high, 3), "low": round(low, 3),
                "change": round(change, 3), "change_pct": round(change_pct, 3),
                "currency": "HKD", "timestamp": datetime.now().isoformat(),
            }

        return None

    except Exception as e:
        logger.debug(f"Sina quote {ticker} failed: {e}")
        return None


# ============================================================
# Unified interface
# ============================================================

class ChinaDataAdapter:
    """
    China-network data adapter.
    Auto-selects an available source, preferring China-reachable APIs.
    Priority:
      US: East Money direct → efinance → Tencent → yfinance
      HK: Tencent → East Money direct → efinance → yfinance
    """

    def __init__(self):
        self.cache: Dict[str, pd.DataFrame] = {}
        self._last_fetch: Dict[str, datetime] = {}
        self._cache_ttl = 300

    def get_historical_data(
        self,
        ticker: str,
        period: str = "2y",
        interval: str = "1d",
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """Fetch historical bars — try sources in priority order."""
        cache_key = f"{ticker}_{period}_{interval}"

        if not force_refresh and cache_key in self.cache:
            last = self._last_fetch.get(cache_key)
            if last and (datetime.now() - last).seconds < self._cache_ttl:
                return self.cache[cache_key]

        market = "HK" if ticker.endswith(".HK") else "US"

        # Priority by market
        if market == "HK":
            sources = [
                ("Tencent", lambda: get_history_tencent(ticker, period, interval)),
                ("East Money", lambda: get_history_eastmoney(ticker, period, interval)),
                ("efinance", lambda: get_history_efinance(ticker, period, interval)),
            ]
        else:
            sources = [
                ("East Money", lambda: get_history_eastmoney(ticker, period, interval)),
                ("efinance", lambda: get_history_efinance(ticker, period, interval)),
                ("Tencent", lambda: get_history_tencent(ticker, period, interval)),
            ]

        # Try China-reachable sources in order
        for name, fn in sources:
            try:
                df = fn()
                if not df.empty and len(df) >= 5:
                    self.cache[cache_key] = df
                    self._last_fetch[cache_key] = datetime.now()
                    return df
            except Exception:
                continue

        # Last resort: yfinance
        df = get_history_yfinance(ticker, period, interval)
        if not df.empty:
            self.cache[cache_key] = df
            self._last_fetch[cache_key] = datetime.now()

        return df

    def health_check(self) -> Dict[str, bool | str]:
        """
        Quickly probe reachability of each data source.

        Uses a light ticker (SPY) with a 5-second timeout per source.
        Failures do not block; returns per-source status and the current primary.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        test_ticker = "SPY"
        sources: Dict[str, bool] = {}

        def _probe(name: str, fn) -> tuple:
            """Probe a single source with a 5-second timeout."""
            try:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(fn)
                    df = future.result(timeout=5)
                if df is not None and not df.empty and len(df) >= 3:
                    return (name, True)
            except Exception:
                pass
            return (name, False)

        # Probe all sources in parallel (light request: last 1 month only)
        period = "1mo"
        probes = [
            ("eastmoney", lambda: get_history_eastmoney(test_ticker, period=period)),
            ("efinance", lambda: get_history_efinance(test_ticker, period=period)),
            ("tencent", lambda: get_history_tencent(test_ticker, period=period)),
            ("yfinance", lambda: get_history_yfinance(test_ticker, period=period)),
        ]

        results: Dict[str, bool] = {}
        with ThreadPoolExecutor(max_workers=len(probes)) as executor:
            future_map = {executor.submit(_probe, name, fn): name for name, fn in probes}
            for future in as_completed(future_map, timeout=10):
                try:
                    name, ok = future.result(timeout=5)
                    results[name] = ok
                except Exception:
                    results[future_map[future]] = False

        # Ensure every source has a result
        for name, _ in probes:
            results.setdefault(name, False)

        # Primary = first available source by priority
        primary = "yfinance"  # default fallback
        priority = ["eastmoney", "efinance", "tencent", "yfinance"]
        for src in priority:
            if results.get(src, False):
                primary = src
                break

        return {**results, "primary": primary}

    def get_realtime_quote(self, ticker: str) -> Optional[Dict]:
        """Fetch a realtime quote — Tencent first, Sina fallback."""
        # Tencent
        quote = get_realtime_quote_tencent(ticker)
        if quote and quote.get("price", 0) > 0:
            return quote

        # Sina
        quote = get_realtime_quote_sina(ticker)
        if quote and quote.get("price", 0) > 0:
            return quote

        # yfinance
        try:
            import yfinance as yf
            stock = yf.Ticker(ticker)
            info = stock.info
            market = "HK" if ticker.endswith(".HK") else "US"
            return {
                "ticker": ticker, "name": info.get("shortName", ticker),
                "market": market,
                "price": info.get("currentPrice", info.get("regularMarketPrice")),
                "change": info.get("regularMarketChange"),
                "change_pct": info.get("regularMarketChangePercent"),
                "volume": info.get("regularMarketVolume"),
                "currency": "HKD" if market == "HK" else "USD",
                "timestamp": datetime.now().isoformat(),
            }
        except Exception:
            return None


# Global singleton
china_data_adapter = ChinaDataAdapter()
