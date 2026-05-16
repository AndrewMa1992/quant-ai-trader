"""
实时行情推流引擎
作为真实市场数据的模拟层 + WebSocket 推流源
"""
import asyncio
import time
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional
import pandas as pd
import numpy as np
from loguru import logger

from backend.config import data_config, model_config
from backend.data_engine.market_data import MarketDataEngine
from backend.data_engine.data_pipeline import DataPipeline


class RealtimeEngine:
    """
    实时行情引擎
    - 模拟实时数据推流（基于历史数据 + 随机噪声）
    - 真实模式对接 Tiger Brokers 实时行情
    - 自定频次推送（1min/5min/1day）
    """

    def __init__(self, market_data: MarketDataEngine, pipeline: DataPipeline):
        self.market_data = market_data
        self.pipeline = pipeline
        self._callbacks: Dict[str, List[Callable]] = {
            "tick": [],      # 每次数据更新
            "signal": [],    # 信号生成
            "error": [],     # 错误
        }
        self._running = False
        self._tick_interval = data_config.UPDATE_INTERVAL  # 秒
        self._base_data: Dict[str, pd.DataFrame] = {}
        self._current_prices: Dict[str, float] = {}
        self._last_update: Dict[str, datetime] = {}

    # ================================================================
    # 事件注册
    # ================================================================

    def on_tick(self, callback: Callable):
        """注册 tick 回调"""
        self._callbacks["tick"].append(callback)

    def on_signal(self, callback: Callable):
        """注册信号回调"""
        self._callbacks["signal"].append(callback)

    def on_error(self, callback: Callable):
        """注册错误回调"""
        self._callbacks["error"].append(callback)

    # ================================================================
    # 引擎控制
    # ================================================================

    async def start(self):
        """
        启动实时行情引擎
        首次运行会加载历史数据作为基础，然后开始模拟推流
        """
        logger.info("🚀 启动实时行情引擎...")

        # 加载初始数据
        await self._load_initial_data()

        self._running = True
        logger.info(f"✅ 实时行情引擎已启动 (间隔: {self._tick_interval}s)")

        # 主循环
        while self._running:
            try:
                await self._process_tick()
                await asyncio.sleep(self._tick_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ 实时引擎错误: {e}")
                self._emit("error", {"error": str(e)})

    def stop(self):
        """停止引擎"""
        self._running = False
        logger.info("⏹️ 实时行情引擎已停止")

    # ================================================================
    # 数据生成
    # ================================================================

    def _generate_simulated_tick(self, ticker: str) -> Dict:
        """
        基于历史数据生成模拟实时 tick
        使用随机游走 + 均值回归生成逼真的价格变动
        """
        if ticker not in self._base_data or self._base_data[ticker].empty:
            return {}

        base = self._base_data[ticker]
        last_close = base["close"].iloc[-1]
        base_volatility = base["returns_1d"].std() if "returns_1d" in base.columns else 0.02

        # 当前价格（带随机噪声）
        current_price = self._current_prices.get(ticker, float(last_close))
        noise = np.random.normal(0, base_volatility / np.sqrt(78))  # 分钟级噪声
        # 均值回归力
        mean_revert = 0.01 * (float(last_close) - current_price) / float(last_close)
        new_price = current_price * (1 + noise + mean_revert)

        # 确保价格合理
        new_price = max(new_price, current_price * 0.98)
        new_price = min(new_price, current_price * 1.02)

        self._current_prices[ticker] = new_price

        # 模拟成交量
        avg_volume = base["volume"].mean()
        volume_intensity = np.random.exponential(1.5)
        simulated_volume = int(avg_volume * volume_intensity / 78)  # 分钟级

        tick = {
            "ticker": ticker,
            "display": self.market_data.get_display_symbol(ticker),
            "market": self.market_data.detect_market(ticker),
            "price": round(new_price, 2),
            "change": round(new_price - current_price, 2),
            "change_pct": round((new_price / current_price - 1) * 100, 3),
            "volume": max(simulated_volume, 0),
            "timestamp": datetime.now().isoformat(),
            "is_simulated": True,
        }

        self._last_update[ticker] = datetime.now()
        return tick

    async def _process_tick(self):
        """处理一次 tick 更新，支持多市场"""
        ticks = []
        for ticker in data_config.ALL_TICKERS:
            tick = self._generate_simulated_tick(ticker)
            if tick:
                ticks.append(tick)

        if ticks:
            self._emit("tick", ticks)

    async def _load_initial_data(self):
        """加载初始数据作为模拟基准"""
        for ticker in data_config.ALL_TICKERS:
            df = self.market_data.get_historical_data(ticker, period="2y", interval="1d")
            if not df.empty:
                # 计算特征
                df = self.pipeline.process(df)
                self._base_data[ticker] = df
                self._current_prices[ticker] = float(df["close"].iloc[-1])
                logger.info(f"📊 {ticker}: 基础数据加载完成 (当前价格: ${self._current_prices[ticker]:.2f})")

        logger.info(f"✅ 共加载 {len(self._base_data)} 只股票的基础数据")

    def _emit(self, event: str, data):
        """发射事件到所有注册的回调"""
        for cb in self._callbacks.get(event, []):
            try:
                cb(data)
            except Exception as e:
                logger.error(f"❌ 回调执行错误: {e}")

    # ================================================================
    # 数据查询
    # ================================================================

    def get_current_price(self, ticker: str) -> Optional[float]:
        """获取当前模拟价格"""
        return self._current_prices.get(ticker)

    def get_base_data(self, ticker: str) -> Optional[pd.DataFrame]:
        """获取基础历史数据"""
        return self._base_data.get(ticker)

    def get_status(self) -> Dict:
        """获取引擎状态"""
        return {
            "running": self._running,
            "tickers": len(self._current_prices),
            "last_update": {t: str(dt) for t, dt in self._last_update.items()},
            "current_prices": {t: round(p, 2) for t, p in self._current_prices.items()},
            "interval": self._tick_interval,
        }
