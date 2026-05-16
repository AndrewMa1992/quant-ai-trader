"""
市场数据引擎 - 对标顶级量化基金的数据获取层
当前使用 yfinance（免费），预留 Tiger Brokers SDK 集成
"""
import time
from datetime import datetime
from typing import Dict, List, Optional
import pandas as pd
import yfinance as yf
from loguru import logger

from backend.config import data_config


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
        return "US"

    @staticmethod
    def get_yfinance_symbol(ticker: str) -> str:
        """转为 yfinance 可识别的 symbol"""
        # yfinance 港股格式：0700.HK
        return ticker

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

        Args:
            ticker: 股票代码（美股: AAPL, 港股: 0700.HK）
            period: 1d/5d/1mo/3mo/6mo/1y/2y/5y/10y/ytd/max
            interval: 1m/2m/5m/15m/30m/60m/1d/5d/1wk/1mo/3mo
            force_refresh: 强制刷新缓存

        Returns:
            DataFrame with columns: open, high, low, close, volume, ...
        """
        cache_key = f"{ticker}_{period}_{interval}"
        market = self.detect_market(ticker)
        display = self.get_display_symbol(ticker)

        # 缓存命中检查（5分钟内有效）
        if not force_refresh and cache_key in self.cache:
            last_fetch = self._last_fetch.get(cache_key)
            if last_fetch and (datetime.now() - last_fetch).seconds < 300:
                return self.cache[cache_key]

        try:
            logger.info(f"📥 [{market}] {display} 获取历史数据: period={period}, interval={interval}")
            stock = yf.Ticker(ticker)
            df = stock.history(period=period, interval=interval)

            if df.empty:
                logger.warning(f"⚠️ [{market}] {display} 无数据返回")
                return pd.DataFrame()

            # 标准化列名
            df = df.rename(columns={
                "Open": "open", "High": "high", "Low": "low",
                "Close": "close", "Volume": "volume",
                "Dividends": "dividends", "Stock Splits": "stock_splits",
            })

            # 添加标识列
            df["ticker"] = ticker
            df["market"] = market
            df.index.name = "timestamp"

            # 更新缓存
            self.cache[cache_key] = df
            self._last_fetch[cache_key] = datetime.now()

            currency = "USD" if market == "US" else "HKD"
            logger.info(f"✅ [{market}] {display} 获取完成: {len(df)} 行 ({df.index[0].date()} → {df.index[-1].date()}, {currency})")
            return df

        except Exception as e:
            logger.error(f"❌ 获取 {ticker} 数据失败: {e}")
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
        获取实时报价（yfinance 延迟15分钟）
        实盘会用 Tiger Brokers API 替代
        """
        market = self.detect_market(ticker)
        display = self.get_display_symbol(ticker)
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            return {
                "ticker": display,
                "symbol": ticker,
                "market": market,
                "price": info.get("currentPrice", info.get("regularMarketPrice")),
                "change": info.get("regularMarketChange"),
                "change_pct": info.get("regularMarketChangePercent"),
                "volume": info.get("regularMarketVolume"),
                "avg_volume": info.get("averageVolume"),
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
                "currency": "HKD" if market == "HK" else "USD",
                "timestamp": datetime.now().isoformat(),
            }
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
