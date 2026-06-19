"""
市场数据引擎 - 对标顶级量化基金的数据获取层
优先使用中国境内数据源 (efinance + 腾讯/新浪 API)，
yfinance 作为海外网络备选
"""
import os
import re
import time
from datetime import datetime
from typing import Dict, List, Optional
import pandas as pd
from loguru import logger

from backend.config import data_config
from backend.data_engine.china_adapter import china_data_adapter

# ★ 设置缓存到项目本地
_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "cache", "yfinance")
os.makedirs(_CACHE_DIR, exist_ok=True)
os.environ.setdefault("YFINANCE_CACHE_DIR", _CACHE_DIR)

# ★ 港股数字代码映射（去除前导零，如 00700 → 0700）
_HK_DIGIT_MAP = {"00700": "0700", "09988": "9988", "03690": "3690", "09999": "9999",
                 "01810": "1810", "00941": "0941", "00883": "0883", "01299": "1299"}

_KNOWN_HK_SUFFIXES = (".HK", ".SI", ".AX", ".NZ")


class MarketDataEngine:
    """
    市场数据引擎
    - 多市场支持（美股 + 港股）
    - 多数据源统一接口
    - 自动处理交易日历
    - 缓存管理
    """

    def __init__(self):
        self.cache: Dict[str, pd.DataFrame] = {}
        self._last_fetch: Dict[str, datetime] = {}
        self._is_market_open = False

    @staticmethod
    def detect_market(ticker: str) -> str:
        """从 ticker 代码检测市场"""
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
        P0-1: 自动补全港股后缀，确保 yfinance 可识别。

        规则：
        1. 纯数字（如 00700, 09988）→ 去除前导零后添加 .HK，优先查映射表
        2. 不以 .HK/.SI/.AX/.NZ 结尾的纯数字 → 添加 .HK
        3. 已有后缀的直接返回

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
        P0-1: 转为 yfinance 可识别的 symbol。
        自动补全 .HK 后缀（委托给 normalize_ticker）。
        """
        return MarketDataEngine.normalize_ticker(ticker)

    @staticmethod
    def get_display_symbol(ticker: str) -> str:
        """获取展示用代码"""
        return ticker.replace(".HK", "")

    # ================================================================
    # 公开接口
    # ================================================================

    def get_historical_data(
        self,
        ticker: str,
        period: str = "2y",
        interval: str = "1d",
        force_refresh: bool = False
    ) -> pd.DataFrame:
        """
        获取历史K线数据
        优先使用中国境内数据源 (efinance + 腾讯API)，yfinance 备选

        Args:
            ticker: 股票代码（美股: AAPL, 港股: 0700.HK 或 00700）
            period: 1d/5d/1mo/3mo/6mo/1y/2y/5y/10y/ytd/max
            interval: 1m/2m/5m/15m/30m/60m/1d/5d/1wk/1mo/3mo
            force_refresh: 强制刷新缓存

        Returns:
            DataFrame with columns: open, high, low, close, volume, ...
        """
        # ★ P0-1: 自动标准化 ticker
        yf_ticker = self.normalize_ticker(ticker)
        cache_key = f"{yf_ticker}_{period}_{interval}"
        market = self.detect_market(yf_ticker)
        display = self.get_display_symbol(yf_ticker)

        # 缓存命中检查（5分钟内有效）
        if not force_refresh and cache_key in self.cache:
            last_fetch = self._last_fetch.get(cache_key)
            if last_fetch and (datetime.now() - last_fetch).seconds < 300:
                return self.cache[cache_key]

        try:
            logger.info(f"📥 [{market}] {display} 获取历史数据: period={period}, interval={interval}")

            # ★ 优先使用中国境内数据源
            df = china_data_adapter.get_historical_data(yf_ticker, period, interval, force_refresh)

            if df.empty:
                logger.warning(f"⚠️ [{market}] {display} 中国数据源无数据 (ticker={yf_ticker})")
                return pd.DataFrame()

            # 标准化列名 (适配不同数据源的列名差异)
            col_map = {"Open": "open", "High": "high", "Low": "low",
                       "Close": "close", "Volume": "volume",
                       "Dividends": "dividends", "Stock Splits": "stock_splits"}
            for old, new in col_map.items():
                if old in df.columns:
                    df = df.rename(columns={old: new})

            # 添加标识列（如果尚未存在）
            if "ticker" not in df.columns:
                df["ticker"] = yf_ticker
            if "market" not in df.columns:
                df["market"] = market
            if df.index.name is None or df.index.name == "":
                df.index.name = "timestamp"

            # 更新缓存
            self.cache[cache_key] = df
            self._last_fetch[cache_key] = datetime.now()

            currency = "USD" if market == "US" else "HKD"
            logger.info(f"✅ [{market}] {display} 获取完成: {len(df)} 行, {currency}")
            return df

        except Exception as e:
            logger.error(f"❌ 获取 {yf_ticker} 数据失败: {e}")
            return pd.DataFrame()

    def get_multi_ticker_data(
        self,
        tickers: Optional[List[str]] = None,
        period: str = "2y",
        interval: str = "1d"
    ) -> Dict[str, pd.DataFrame]:
        """
        批量获取多股票数据（自动识别美股/港股）

        Returns:
            {ticker: DataFrame}
        """
        if tickers is None:
            tickers = data_config.ALL_TICKERS
        result = {}
        for ticker in tickers:
            df = self.get_historical_data(ticker, period, interval)
            if not df.empty:
                result[ticker] = df
            time.sleep(0.5)
        return result

    def get_realtime_quote(self, ticker: str) -> Optional[Dict]:
        """
        获取实时报价
        优先使用中国境内 API (腾讯/新浪)，yfinance 备选
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
            logger.error(f"❌ [{market}] {display} 获取实时报价失败: {e}")
            return None

    def get_market_status(self) -> Dict:
        """获取所有市场状态"""
        import pytz
        # MARKET_CONFIGS 是 config.py 的模块级变量
        from backend import config as cfg
        market_configs = cfg.MARKET_CONFIGS

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
    # Tiger Brokers 适配器（预留）
    # ================================================================

    def _tiger_get_historical(self, ticker: str, **kwargs) -> pd.DataFrame:
        """
        老虎证券历史数据接口（预留）
        有 API 账号后替换 yfinance 调用
        """
        # from tiger_open_python_sdk import TigerApiClient
        # client = TigerApiClient(...)
        # ...
        raise NotImplementedError("Tiger Brokers SDK 待接入")

    def _tiger_get_realtime(self, ticker: str) -> Dict:
        """老虎证券实时行情接口（预留）"""
        raise NotImplementedError("Tiger Brokers SDK 待接入")


# 全局单例
market_data_engine = MarketDataEngine()
