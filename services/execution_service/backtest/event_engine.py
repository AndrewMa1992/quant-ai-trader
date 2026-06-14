"""services/execution_service/backtest/event_engine.py – Event-driven backtest engine.

Priority queue processing: MarketEvent → SignalEvent → OrderEvent → FillEvent.
Daily OHLCV data; generates simple momentum signals for demonstration.
"""

from __future__ import annotations

import queue
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from services.data_service.storage.parquet_store import ParquetStore
from services.execution_service.backtest.broker import SimulationBroker
from services.execution_service.backtest.events import (
    Event, EventType, MarketEvent, OrderEvent, SignalEvent,
)
from services.execution_service.backtest.metrics import PerformanceMetrics
from services.execution_service.config import exec_config


class BacktestEngine:
    """Event-driven backtest engine.

    Processes events in priority order:
    MARKET(0) → SIGNAL(1) → ORDER(2) → FILL(3)

    Attributes:
        tickers: Backtest universe.
        start_date: Backtest start.
        end_date: Backtest end.
        initial_capital: Starting capital.
        broker: Simulation broker.
    """

    def __init__(
        self,
        tickers: list[str],
        start_date: str = "2023-01-01",
        end_date: str = "2024-12-31",
        initial_capital: float = 1_000_000.0,
    ) -> None:
        self.tickers = tickers
        self.start_date = start_date
        self.end_date = end_date
        self.initial_capital = initial_capital
        self.broker = SimulationBroker(initial_cash=initial_capital)
        self._store = ParquetStore()
        self._equity_curve: list[dict[str, Any]] = []
        self._event_queue: queue.PriorityQueue = queue.PriorityQueue()

    def run(self) -> dict[str, Any]:
        """Execute the backtest.

        Returns:
            Performance result dictionary.
        """
        # Load data for all tickers
        price_data = self._load_price_data()

        if not price_data:
            return {"error": "No data loaded"}

        # Get trading days
        all_dates = sorted(price_data[list(price_data.keys())[0]].index)

        s_date = date.fromisoformat(self.start_date)
        e_date = date.fromisoformat(self.end_date)
        trading_dates = [d for d in all_dates
                         if s_date <= d.date() <= e_date] if hasattr(all_dates[0], 'date') else all_dates

        # Main loop
        for current_date in trading_dates:
            timestamp = datetime.combine(
                current_date if hasattr(current_date, 'date') else current_date,
                datetime.min.time(),
            )

            # 1. Market event
            self._event_queue.put(MarketEvent(timestamp=timestamp))

            while not self._event_queue.empty():
                event = self._event_queue.get()

                if event.event_type == EventType.MARKET:
                    self._handle_market(event, current_date, price_data, timestamp)
                elif event.event_type == EventType.SIGNAL:
                    self._handle_signal(event, current_date, price_data, timestamp)
                elif event.event_type == EventType.ORDER:
                    self._handle_order(event, current_date, price_data, timestamp)

            # Track equity
            prices_snapshot = self._get_current_prices(price_data, current_date)
            total_value = self.broker.get_total_value(prices_snapshot)
            self._equity_curve.append({
                "date": str(current_date)[:10] if hasattr(current_date, 'strftime') else str(current_date),
                "equity": total_value,
                "cash": self.broker.cash,
                "positions": len(self.broker.positions),
            })

        # Compute metrics
        equity = [e["equity"] for e in self._equity_curve]
        metrics = PerformanceMetrics.from_equity_curve(equity)

        return {
            "initial_capital": self.initial_capital,
            "final_value": round(equity[-1], 2) if equity else self.initial_capital,
            "num_dates": len(self._equity_curve),
            **metrics,
        }

    def _load_price_data(self) -> dict[str, pd.DataFrame]:
        """Load price data for all tickers.

        Returns:
            Dict of ticker → OHLCV DataFrame.
        """
        data: dict[str, pd.DataFrame] = {}
        for ticker in self.tickers:
            df = self._store.read_daily(ticker, date.fromisoformat(self.start_date),
                                         date.fromisoformat(self.end_date))
            if df is not None and len(df) > 50:
                data[ticker] = df
        return data

    def _get_current_prices(
        self,
        price_data: dict[str, pd.DataFrame],
        current_date: Any,
    ) -> dict[str, float]:
        """Get current prices for all tickers.

        Args:
            price_data: Loaded price data.
            current_date: Current trading date.

        Returns:
            Dict of ticker → price.
        """
        prices: dict[str, float] = {}
        for ticker, df in price_data.items():
            try:
                col = "adj_close" if "adj_close" in df.columns else "close"
                prices[ticker] = float(df.loc[current_date, col])
            except (KeyError, IndexError):
                prices[ticker] = 0.0
        return prices

    def _handle_market(
        self,
        event: MarketEvent,
        current_date: Any,
        price_data: dict[str, pd.DataFrame],
        timestamp: datetime,
    ) -> None:
        """Generate trading signals from market data."""
        prices = self._get_current_prices(price_data, current_date)

        for ticker in self.tickers:
            df = price_data.get(ticker)
            if df is None:
                continue

            col = "adj_close" if "adj_close" in df.columns else "close"

            try:
                pos = df.index.get_loc(current_date)
                if pos < 63:
                    continue

                # Simple momentum signal
                recent = df[col].iloc[max(0, pos-63):pos+1]
                ret_1m = float(recent.iloc[-1] / recent.iloc[-21]) - 1.0 if len(recent) >= 21 else 0.0
                ret_3m = float(recent.iloc[-1] / recent.iloc[0]) - 1.0 if len(recent) > 0 else 0.0

                signal_val = 0.5 * ret_1m + 0.5 * ret_3m
                signal_val = np.clip(signal_val, -1.0, 1.0)

                if abs(signal_val) > 0.02:
                    direction = "BUY" if signal_val > 0 else "SELL"
                    self._event_queue.put(SignalEvent(
                        ticker=ticker,
                        signal=float(signal_val),
                        confidence=min(abs(signal_val) * 5, 0.9),
                        direction=direction,
                        timestamp=timestamp,
                    ))

            except (KeyError, IndexError):
                continue

    def _handle_signal(
        self,
        event: SignalEvent,
        current_date: Any,
        price_data: dict[str, pd.DataFrame],
        timestamp: datetime,
    ) -> None:
        """Convert signal to order."""
        ticker = event.ticker
        prices = self._get_current_prices(price_data, current_date)
        price = prices.get(ticker, 0)

        if price <= 0:
            return

        # Position sizing: Kelly fraction
        capital_per_trade = self.broker.cash * 0.05  # 5% per position
        quantity = max(10, int(capital_per_trade / price))

        if event.direction == "BUY":
            side = "BUY"
        elif event.direction == "SELL":
            side = "SELL"
        else:
            return

        # Check existing position
        current_pos = self.broker.positions.get(ticker, 0)
        if side == "BUY" and current_pos > 0:
            return
        if side == "SELL" and current_pos <= 0:
            return

        self._event_queue.put(OrderEvent(
            ticker=ticker,
            side=side,
            quantity=quantity,
            order_type="MKT",
            timestamp=timestamp,
        ))

    def _handle_order(
        self,
        event: OrderEvent,
        current_date: Any,
        price_data: dict[str, pd.DataFrame],
        timestamp: datetime,
    ) -> None:
        """Execute order via broker."""
        prices = self._get_current_prices(price_data, current_date)
        price = prices.get(event.ticker, 0)

        if price <= 0:
            return

        df = price_data.get(event.ticker)
        volume = int(df.loc[current_date, "volume"]) if df is not None and current_date in df.index else 100000

        fill = self.broker.execute_order(event, price, volume, timestamp)
        if fill:
            logger.debug(f"FILLED: {fill.side} {fill.quantity} {fill.ticker} @ {fill.price:.2f}")
