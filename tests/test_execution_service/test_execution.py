"""tests/test_execution_service/test_execution.py – Tests for execution algos, circuit breakers, alerts."""

from __future__ import annotations

import numpy as np
import pytest

from services.execution_service.execution.twap import TWAPExecutor
from services.execution_service.execution.vwap import VWAPExecutor
from services.execution_service.execution.pov import POVExecutor
from services.execution_service.live.position_tracker import PositionTracker
from services.execution_service.live.circuit_breaker import CircuitBreaker
from services.execution_service.live.alert_manager import AlertManager
from services.execution_service.live.tiger_broker import TigerBroker


class TestTWAP:
    """Tests for TWAPExecutor."""

    def test_schedule(self):
        twap = TWAPExecutor(total_quantity=1000, side="BUY", n_slices=10)
        schedule = twap.schedule()
        assert len(schedule) == 10
        assert abs(sum(s[0] for s in schedule) - 1.0) < 0.01

    def test_slice_quantity(self):
        twap = TWAPExecutor(total_quantity=1000, side="SELL", n_slices=10)
        assert twap.get_slice_quantity() == 100

    def test_progress(self):
        twap = TWAPExecutor(total_quantity=1000, side="BUY")
        twap.record_fill(500)
        assert twap.progress() == 0.5
        assert twap.remaining_quantity() == 500

    def test_cancel(self):
        twap = TWAPExecutor(total_quantity=1000, side="BUY")
        twap.cancel()
        assert twap.is_cancelled


class TestVWAP:
    """Tests for VWAPExecutor."""

    def test_schedule(self):
        vwap = VWAPExecutor(total_quantity=5000, side="BUY", n_buckets=13)
        schedule = vwap.schedule()
        assert len(schedule) == 13
        assert abs(sum(s[0] for s in schedule) - 1.0) < 0.02

    def test_default_volume_profile(self):
        vwap = VWAPExecutor(total_quantity=1000, side="BUY", n_buckets=26)
        profile = vwap._default_volume_profile()
        assert len(profile) == 26
        assert abs(sum(profile) - 1.0) < 0.01


class TestPOV:
    """Tests for POVExecutor."""

    def test_compute_slice_quantity(self):
        pov = POVExecutor(total_quantity=5000, side="BUY", target_rate=0.20)
        qty = pov.compute_slice_quantity(market_volume=50000)
        assert qty == 5000  # min(20% of 50000=10000, remaining=5000) → 5000

    def test_compute_slice_capped_by_remaining(self):
        pov = POVExecutor(total_quantity=100, side="BUY", target_rate=0.20)
        pov.record_fill(90)
        qty = pov.compute_slice_quantity(market_volume=100000)
        assert qty <= 10  # Only 10 remaining


class TestPositionTracker:
    """Tests for PositionTracker."""

    def test_record_buy(self):
        pt = PositionTracker()
        pt.record_order({"ticker": "AAPL", "side": "BUY", "quantity": 100, "price": 150.0, "status": "FILLED"})
        positions = pt.get_positions()
        assert len(positions) == 1
        assert positions[0]["ticker"] == "AAPL"

    def test_get_summary(self):
        pt = PositionTracker()
        pt.record_order({"ticker": "AAPL", "side": "BUY", "quantity": 100, "price": 150.0, "status": "FILLED"})
        summary = pt.get_summary()
        assert summary["position_count"] == 1


class TestCircuitBreaker:
    """Tests for CircuitBreaker."""

    def test_allow_order_default(self):
        cb = CircuitBreaker()
        cb.set_nav(1_000_000)
        assert cb.allow_order("AAPL", 100) is True

    def test_daily_loss_halt(self):
        cb = CircuitBreaker(daily_loss_limit=0.05)
        cb.set_nav(1_000_000)
        cb._current_nav = 940_000  # -6%
        assert cb.allow_order("AAPL", 100) is False

    def test_consecutive_loss_cooling(self):
        cb = CircuitBreaker(consecutive_loss_limit=3, cooling_minutes=30)
        cb.record_trade(-1000)
        cb.record_trade(-500)
        cb.record_trade(-200)
        assert cb._consecutive_losses == 3

    def test_win_resets_consecutive(self):
        cb = CircuitBreaker(consecutive_loss_limit=3)
        cb.record_trade(-1000)
        cb.record_trade(-500)
        cb.record_trade(300)  # Win
        assert cb._consecutive_losses == 0

    def test_reset(self):
        cb = CircuitBreaker()
        cb.set_nav(1_000_000)
        cb._current_nav = 940_000
        cb._halted = True
        cb.reset()
        assert cb._halted is False


class TestAlertManager:
    """Tests for AlertManager."""

    def test_send_info(self):
        am = AlertManager(max_recent=10)
        alert = am.send("Test message", severity="INFO", source="test")
        assert alert["severity"] == "INFO"
        assert alert["message"] == "Test message"

    def test_get_recent(self):
        am = AlertManager(max_recent=10)
        am.send("Info 1", severity="INFO")
        am.send("Warn 1", severity="WARN")
        alerts = am.get_recent(severity="WARN")
        assert len(alerts) == 1

    def test_summary(self):
        am = AlertManager(max_recent=10)
        am.send("Info", severity="INFO")
        am.send("Warn", severity="WARN")
        am.send("Crit", severity="CRITICAL")
        summary = am.get_summary()
        assert summary["INFO"] == 1
        assert summary["CRITICAL"] == 1


class TestTigerBroker:
    """Tests for TigerBroker (paper mode)."""

    @pytest.mark.asyncio
    async def test_place_paper_order(self):
        broker = TigerBroker(account="20874631", require_confirm=False)
        result = await broker.place_order("AAPL", "BUY", 100)
        assert result["ticker"] == "AAPL"
        assert result["status"] in ("PAPER_SUBMITTED", "PENDING_CONFIRMATION")

    @pytest.mark.asyncio
    async def test_cancel_paper_order(self):
        broker = TigerBroker(account="20874631", require_confirm=False)
        result = await broker.cancel_order("test-order-id")
        assert result["status"] == "PAPER_CANCELLED"
