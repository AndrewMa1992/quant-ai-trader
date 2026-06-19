"""
中国网络适配器 — 替代 yfinance 的数据源
优先使用中国境内可访问的 API：
  - efinance / 东方财富直连 API 用于美股历史数据 (需在中国大陆)
  - 腾讯财经 API (qt.gtimg.cn) 用于港股历史 + 全市场实时行情
  - 新浪财经 API (hq.sinajs.cn) 作为实时行情备选
  - yfinance 作为海外网络最终备选

所有中国境内 API 均不依赖 Google/Yahoo 等被墙服务。
数据源会按优先级自动切换，适配不同网络环境。
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
# 东方财富直连 API (比 efinance 更可控)
# ============================================================
_EASTMONEY_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
_EASTMONEY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Referer": "https://quote.eastmoney.com/",
}

# 腾讯财经 API
_TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
_TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="


def _eastmoney_secid(ticker: str) -> str:
    """转换为东方财富 secid 格式: 市场.代码 — 港股5位"""
    if ticker.endswith(".HK"):
        code = ticker.replace(".HK", "").zfill(5)
        return f"116.{code}"  # 港股
    if ticker.endswith(".SI"):
        code = ticker.replace(".SI", "")
        return f"122.{code}"  # 新加坡
    # 美股: 105=纳斯达克, 106=NYSE
    return f"105.{ticker}"


def _tencent_kline_code(ticker: str) -> str:
    """转换为腾讯 KLine API 代码 — 港股必须是5位数字"""
    if ticker.endswith(".HK"):
        code = ticker.replace(".HK", "")
        # 港股代码必须5位，左补零: 0700 → 00700
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
    """转换为腾讯实时行情代码 — 港股5位数字"""
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
# 历史数据获取 — 东方财富直连
# ============================================================

def get_history_eastmoney(
    ticker: str,
    period: str = "2y",
    interval: str = "1d",
) -> pd.DataFrame:
    """
    通过东方财富 API 获取历史K线（美股+港股均可用）
    需要在中国大陆或有东方财富 API 访问权限
    """
    secid = _eastmoney_secid(ticker)
    market = "HK" if ticker.endswith(".HK") else "US"

    # period → 数据条数
    period_map = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "5y": 1250, "10y": 2500}
    count = period_map.get(period, 730)

    # interval → klt
    klt_map = {"1d": 101, "1wk": 102, "1mo": 103}
    klt = klt_map.get(interval, 101)

    # 日期范围
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
        "fqt": 1,  # 前复权
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

        logger.info(f"✅ [东方财富] {ticker} 获取完成: {len(df)} 行")
        return df

    except Exception as e:
        logger.debug(f"东方财富 API {ticker} 失败: {e}")
        return pd.DataFrame()


# ============================================================
# 历史数据获取 — 腾讯财经
# ============================================================

def get_history_tencent(
    ticker: str,
    period: str = "2y",
    interval: str = "1d",
) -> pd.DataFrame:
    """
    通过腾讯财经 API 获取历史K线
    港股效果好（全量数据），美股只有少量数据点
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
            return pd.DataFrame()  # 腾讯美股只返回1-2个点，不采用

        # 腾讯数据可能有7列（第7列是分红信息dict），只取前6列
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

        logger.info(f"✅ [腾讯] {ticker} 获取完成: {len(df)} 行")
        return df

    except Exception as e:
        logger.debug(f"腾讯 API {ticker} 失败: {e}")
        return pd.DataFrame()


# ============================================================
# 历史数据获取 — efinance
# ============================================================

def get_history_efinance(
    ticker: str,
    period: str = "2y",
    interval: str = "1d",
) -> pd.DataFrame:
    """通过 efinance 获取历史数据（美股效果好，港股不稳定）"""
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

        df = df.rename(columns={
            "日期": "timestamp", "开盘": "open", "收盘": "close",
            "最高": "high", "最低": "low", "成交量": "volume",
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

        logger.info(f"✅ [efinance] {ticker} 获取完成: {len(df)} 行")
        return df

    except Exception as e:
        logger.debug(f"efinance {ticker} 失败: {e}")
        return pd.DataFrame()


# ============================================================
# 历史数据获取 — yfinance (海外备选)
# ============================================================

def get_history_yfinance(
    ticker: str,
    period: str = "2y",
    interval: str = "1d",
) -> pd.DataFrame:
    """yfinance 最终备选（仅海外网络可用）"""
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

        logger.info(f"✅ [yfinance] {ticker} 获取完成: {len(raw)} 行")
        return raw

    except Exception as e:
        logger.debug(f"yfinance {ticker} 失败: {e}")
        return pd.DataFrame()


# ============================================================
# 实时行情获取 — 腾讯财经
# ============================================================

def get_realtime_quote_tencent(ticker: str) -> Optional[Dict]:
    """通过腾讯财经 API 获取实时行情"""
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
        logger.debug(f"腾讯行情 {ticker} 失败: {e}")
        return None


# ============================================================
# 实时行情获取 — 新浪财经
# ============================================================

def get_realtime_quote_sina(ticker: str) -> Optional[Dict]:
    """通过新浪财经 API 获取实时行情"""
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
        logger.debug(f"新浪行情 {ticker} 失败: {e}")
        return None


# ============================================================
# 统一接口
# ============================================================

class ChinaDataAdapter:
    """
    中国网络数据适配器
    自动选择可用的数据源，优先中国境内 API
    数据源优先级：
      美股: 东方财富直连 → efinance → 腾讯 → yfinance
      港股: 腾讯 → 东方财富直连 → efinance → yfinance
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
        """获取历史K线 — 按优先级尝试各数据源"""
        cache_key = f"{ticker}_{period}_{interval}"

        if not force_refresh and cache_key in self.cache:
            last = self._last_fetch.get(cache_key)
            if last and (datetime.now() - last).seconds < self._cache_ttl:
                return self.cache[cache_key]

        market = "HK" if ticker.endswith(".HK") else "US"

        # 按市场选择优先级
        if market == "HK":
            sources = [
                ("腾讯", lambda: get_history_tencent(ticker, period, interval)),
                ("东方财富", lambda: get_history_eastmoney(ticker, period, interval)),
                ("efinance", lambda: get_history_efinance(ticker, period, interval)),
            ]
        else:
            sources = [
                ("东方财富", lambda: get_history_eastmoney(ticker, period, interval)),
                ("efinance", lambda: get_history_efinance(ticker, period, interval)),
                ("腾讯", lambda: get_history_tencent(ticker, period, interval)),
            ]

        # 依次尝试中国境内数据源
        for name, fn in sources:
            try:
                df = fn()
                if not df.empty and len(df) >= 5:
                    self.cache[cache_key] = df
                    self._last_fetch[cache_key] = datetime.now()
                    return df
            except Exception:
                continue

        # 最终备选: yfinance
        df = get_history_yfinance(ticker, period, interval)
        if not df.empty:
            self.cache[cache_key] = df
            self._last_fetch[cache_key] = datetime.now()

        return df

    def health_check(self) -> Dict[str, bool | str]:
        """
        快速探测各数据源可达性
        
        使用轻量 ticker (SPY) 快速测试各源，每个源 5 秒超时。
        失败不阻塞，返回各源状态和当前主数据源。
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        test_ticker = "SPY"
        sources: Dict[str, bool] = {}

        def _probe(name: str, fn) -> tuple:
            """探测单个数据源，5秒超时"""
            try:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(fn)
                    df = future.result(timeout=5)
                if df is not None and not df.empty and len(df) >= 3:
                    return (name, True)
            except Exception:
                pass
            return (name, False)

        # 并行探测所有源（轻量请求：仅最近 1 月数据）
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

        # 确保所有源都有结果
        for name, _ in probes:
            results.setdefault(name, False)

        # 确定主数据源（按优先级第一个可用的）
        primary = "yfinance"  # 默认回退
        priority = ["eastmoney", "efinance", "tencent", "yfinance"]
        for src in priority:
            if results.get(src, False):
                primary = src
                break

        return {**results, "primary": primary}

    def get_realtime_quote(self, ticker: str) -> Optional[Dict]:
        """获取实时行情 — 腾讯优先，新浪备选"""
        # 腾讯
        quote = get_realtime_quote_tencent(ticker)
        if quote and quote.get("price", 0) > 0:
            return quote

        # 新浪
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


# 全局单例
china_data_adapter = ChinaDataAdapter()
