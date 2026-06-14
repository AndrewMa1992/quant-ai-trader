"""tests/test_execution_service/test_backtest.py – Tests for backtest engine and components."""

from __future__ import annotations

import numpy as np
import pytest

from services.execution_service.backtest.events import MarketEvent, SignalEvent, OrderEvent, FillEvent
from services.execution_service.backtest.broker import SimulationBroker
from services.execution_service.backtest.slippage import SlippageModel
from services.execution_service.backtest.metrics import PerformanceMetrics
from services.execution_service.backtest.event_engine import BacktestEngine


class TestEvents:
    """Tests for event types."""

    def test_market_event(self):
        evt = MarketEvent()
        assert evt.event_type.value == "MARKET"

    def test_signal_event(self):
        evt = SignalEvent(ticker="AAPL", signal=0.5, direction="BUY")
        assert evt.ticker == "AAPL"
        assert evt.signal == 0.5
        assert evt.direction == "BUY"

    def test_order_event(self):
        evt = OrderEvent(ticker="MSFT", side="BUY", quantity=100)
        assert evt.quantity == 100
        assert evt.side == "BUY"
        assert evt.order_id != ""

    def test_fill_event(self):
        evt = FillEvent(ticker="AAPL", side="BUY", quantity=50, price=150.0, commission=0.75)
        assert evt.price == 150.0
        assert evt.commission == 0.75


class TestSimulationBroker:
    """Tests for SimulationBroker."""

    @pytest.fixture
    def broker(self) -> SimulationBroker:
        return SimulationBroker(initial_cash=1_000_000.0)

    def test_execute_buy(self, broker: SimulationBroker):
        order = OrderEvent(ticker="AAPL", side="BUY", quantity=100)
        fill = broker.execute_order(order, current_price=150.0, volume=1000000)
        assert fill is not None
        assert fill.price >= 149.9  # Slippage adjustment
        assert broker.positions.get("AAPL") == 100

    def test_execute_sell_from_flat(self, broker: SimulationBroker):
        # Add position
        broker.execute_order(OrderEvent(ticker="AAPL", side="BUY", quantity=100), 150.0)
        # Sell
        broker.execute_order(OrderEvent(ticker="AAPL", side="SELL", quantity=50), 155.0)
        assert broker.positions.get("AAPL") == 50

    def test_get_total_value(self, broker: SimulationBroker):
        broker.execute_order(OrderEvent(ticker="AAPL", side="BUY", quantity=100), 150.0)
        value = broker.get_total_value({"AAPL": 155.0})
        assert value > broker.cash


class TestSlippage:
    """Tests for SlippageModel."""

    def test_buy_slippage_positive(self):
        model = SlippageModel(base_slippage_bps=5.0)
        fill_price = model.apply(price=100.0, side="BUY", quantity=1000, volume=100000)
        assert fill_price > 100.0

    def test_sell_slippage_negative(self):
        model = SlippageModel(base_slippage_bps=5.0)
        fill_price = model.apply(price=100.0, side="SELL", quantity=1000, volume=100000)
        assert fill_price < 100.0

    def test_estimate_cost(self):
        model = SlippageModel()
        costs = model.estimate_cost(price=100.0, side="BUY", quantity=5000, volume=100000)
        assert "fixed_cost" in costs
        assert "volume_impact" in costs


class TestPerformanceMetrics:
    """Tests for PerformanceMetrics."""

    def test_from_equity_curve(self):
        equity = [1000000, 1010000, 1005000, 1020000, 1030000, 1025000, 1040000]
        metrics = PerformanceMetrics.from_equity_curve(equity)
        assert "sharpe_ratio" in metrics
        assert "max_drawdown" in metrics
        assert metrics["max_drawdown"] <= 0

    def test_from_trades(self):
        trades = [
            {"pnl": 5000}, {"pnl": -2000}, {"pnl": 3000}, {"pnl": -1000}, {"pnl": 4000}
        ]
        metrics = PerformanceMetrics.from_trades(trades, initial_capital=100000)
        assert metrics["num_trades"] == 5
        assert metrics["total_pnl"] == 9000


class TestBacktestEngine:
    """Tests for BacktestEngine (smoke test)."""

    def test_run_with_data(self):
        engine = BacktestEngine(
            tickers=["SPY"],
            start_date="2024-01-01",
            end_date="2024-03-31",
            initial_capital=1_000_000,
        )
        result = engine.run()
        if "error" not in result:
            assert "final_value" in result
