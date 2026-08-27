"""
Realtime quote streaming engine.
Acts as a simulated market-data layer plus a WebSocket push source.
"""
import asyncio
from datetime import datetime
from typing import Callable, Dict, List, Optional
import pandas as pd
import numpy as np
from loguru import logger

from configs.settings import settings
from backend.data_engine.market_data import MarketDataEngine
from backend.data_engine.data_pipeline import DataPipeline


class RealtimeEngine:
    """
    Realtime quote engine.
    - Simulate realtime streaming (historical data + random noise)
    - Live mode can connect to Tiger Brokers realtime quotes
    - Configurable push frequency (1min/5min/1day)
    """

    def __init__(self, market_data: MarketDataEngine, pipeline: DataPipeline):
        self.market_data = market_data
        self.pipeline = pipeline
        self._callbacks: Dict[str, List[Callable]] = {
            "tick": [],      # every data update
            "signal": [],    # signal generation
            "error": [],     # errors
        }
        self._running = False
        self._tick_interval = settings.DATA_UPDATE_INTERVAL  # seconds
        self._base_data: Dict[str, pd.DataFrame] = {}
        self._current_prices: Dict[str, float] = {}
        self._last_update: Dict[str, datetime] = {}

    # ================================================================
    # Event registration
    # ================================================================

    def on_tick(self, callback: Callable):
        """Register a tick callback."""
        self._callbacks["tick"].append(callback)

    def on_signal(self, callback: Callable):
        """Register a signal callback."""
        self._callbacks["signal"].append(callback)

    def on_error(self, callback: Callable):
        """Register an error callback."""
        self._callbacks["error"].append(callback)

    # ================================================================
    # Engine control
    # ================================================================

    async def start(self):
        """
        Start the realtime quote engine.
        First run loads historical data as a baseline, then starts simulated streaming.
        """
        logger.info("🚀 Starting realtime quote engine...")

        # Load initial data
        await self._load_initial_data()

        self._running = True
        logger.info(f"✅ Realtime quote engine started (interval: {self._tick_interval}s)")

        # Main loop
        while self._running:
            try:
                await self._process_tick()
                await asyncio.sleep(self._tick_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Realtime engine error: {e}")
                self._emit("error", {"error": str(e)})

    def stop(self):
        """Stop the engine."""
        self._running = False
        logger.info("⏹️ Realtime quote engine stopped")

    # ================================================================
    # Data generation
    # ================================================================

    def _generate_simulated_tick(self, ticker: str) -> Dict:
        """
        Generate a simulated realtime tick from historical data.
        Uses random walk + mean reversion for realistic price moves.
        """
        if ticker not in self._base_data or self._base_data[ticker].empty:
            return {}

        base = self._base_data[ticker]
        last_close = base["close"].iloc[-1]
        base_volatility = base["returns_1d"].std() if "returns_1d" in base.columns else 0.02

        # Current price (with random noise)
        current_price = self._current_prices.get(ticker, float(last_close))
        noise = np.random.normal(0, base_volatility / np.sqrt(78))  # minute-level noise
        # Mean-reversion force
        mean_revert = 0.01 * (float(last_close) - current_price) / float(last_close)
        new_price = current_price * (1 + noise + mean_revert)

        # Keep prices in a reasonable band
        new_price = max(new_price, current_price * 0.98)
        new_price = min(new_price, current_price * 1.02)

        self._current_prices[ticker] = new_price

        # Simulated volume
        avg_volume = base["volume"].mean()
        volume_intensity = np.random.exponential(1.5)
        simulated_volume = int(avg_volume * volume_intensity / 78)  # minute-level

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
        """Process one tick update across markets."""
        ticks = []
        for ticker in settings.DATA_ALL_TICKERS:
            tick = self._generate_simulated_tick(ticker)
            if tick:
                ticks.append(tick)

        if ticks:
            self._emit("tick", ticks)

    async def _load_initial_data(self):
        """Load baseline historical data for simulation (non-blocking)."""
        import concurrent.futures
        loop = asyncio.get_running_loop()

        async def _load_one(ticker):
            try:
                df = await loop.run_in_executor(
                    None,
                    lambda: self.market_data.get_historical_data(ticker, period="2y", interval="1d"),
                )
                if not df.empty:
                    df = await loop.run_in_executor(None, lambda: self.pipeline.process(df))
                    self._base_data[ticker] = df
                    self._current_prices[ticker] = float(df["close"].iloc[-1])
                    logger.info(f"📊 {ticker}: baseline data loaded (last price: ${self._current_prices[ticker]:.2f})")
            except Exception as e:
                logger.warning(f"⚠️ {ticker} data load failed: {e}")

        for ticker in settings.DATA_ALL_TICKERS:
            await _load_one(ticker)
            # Yield the event loop so HTTP requests are not blocked
            await asyncio.sleep(0)

        logger.info(f"✅ Loaded baseline data for {len(self._base_data)} stocks")

    def _emit(self, event: str, data):
        """Emit an event to all registered callbacks."""
        for cb in self._callbacks.get(event, []):
            try:
                cb(data)
            except Exception as e:
                logger.error(f"❌ Callback error: {e}")

    # ================================================================
    # Data queries
    # ================================================================

    def get_current_price(self, ticker: str) -> Optional[float]:
        """Return the current simulated price."""
        return self._current_prices.get(ticker)

    def get_base_data(self, ticker: str) -> Optional[pd.DataFrame]:
        """Return baseline historical data."""
        return self._base_data.get(ticker)

    def get_status(self) -> Dict:
        """Return engine status."""
        return {
            "running": self._running,
            "tickers": len(self._current_prices),
            "last_update": {t: str(dt) for t, dt in self._last_update.items()},
            "current_prices": {t: round(p, 2) for t, p in self._current_prices.items()},
            "interval": self._tick_interval,
        }
