"""Regression tests for RiskGate URL/fail-mode and liquidation sync fixes."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.risk_gate import RiskGate
from shared.risk_manager import RiskManager
from shared.portfolio_manager import PortfolioManager


class _DummyCB:
    def allow_order(self, ticker, quantity, price=None):
        return True


def test_risk_gate_portfolio_weights():
    gate = RiskGate(circuit_breaker=_DummyCB(), risk_service_url="http://localhost:8015")
    tickers, weights = gate._portfolio_tickers_weights(
        {
            "total_value": 10000.0,
            "positions": {"AAPL": 10, "MSFT": 5},
            "position_values": {"AAPL": 7000.0, "MSFT": 3000.0},
        }
    )
    assert "AAPL" in tickers and "MSFT" in tickers
    parts = [float(x) for x in weights.split(",")]
    assert abs(sum(parts) - 1.0) < 1e-6


def test_risk_gate_fail_closed_live(monkeypatch):
    from configs import pipeline_config as pc

    monkeypatch.setattr(pc.pipeline_config, "EXECUTION_MODE", "live")
    gate = RiskGate(circuit_breaker=_DummyCB(), risk_service_url="http://localhost:8015")
    result = gate._on_check_failure("VaR down")
    assert result["passed"] is False


def test_risk_gate_fail_open_paper(monkeypatch):
    from configs import pipeline_config as pc

    monkeypatch.setattr(pc.pipeline_config, "EXECUTION_MODE", "paper")
    gate = RiskGate(circuit_breaker=_DummyCB(), risk_service_url="http://localhost:8015")
    result = gate._on_check_failure("VaR down")
    assert result["passed"] is True
    assert "warning" in result


def test_liquidation_requires_synced_positions():
    rm = RiskManager(initial_capital=100_000)
    # Without positions, liquidate_all is a no-op
    assert rm.liquidate_all({"AAPL": 100.0}, tiger_bridge=_DummyTiger()) == []

    rm.update_portfolio_state(
        portfolio_value=110_000,
        cash=10_000,
        positions={"AAPL": 100},
        prices={"AAPL": 100.0},
    )
    records = rm.liquidate_all({"AAPL": 100.0}, tiger_bridge=_DummyTiger())
    assert len(records) == 1
    assert records[0]["ticker"] == "AAPL"
    assert rm.positions.get("AAPL", 0) == 0


def test_portfolio_apply_liquidation():
    pm = PortfolioManager(initial_capital=100_000)
    pm.positions["AAPL"] = 50
    pm.avg_costs["AAPL"] = 100.0
    pm.cash = 50_000
    pm.apply_liquidation(
        [{"ticker": "AAPL", "shares": 50, "price": 110.0, "side": "sell"}],
        prices={"AAPL": 110.0},
    )
    assert "AAPL" not in pm.positions or pm.positions.get("AAPL", 0) == 0
    assert pm.cash > 50_000


def test_extreme_dd_after_sync_triggers():
    from shared.kill_switch import get_kill_switch

    rm = RiskManager(initial_capital=1_000_000)
    rm.portfolio_value = 50_000
    rm.peak_value = 1_000_000
    rm.daily_start_value = 50_000  # neutralize daily loss
    rm._tiger_synced = True
    report = rm.check_circuit_breaker()
    assert report.circuit_breaker is True
    # Institutional path engages durable kill switch — reset for other tests
    rm.force_reset_circuit()
    if get_kill_switch().engaged:
        get_kill_switch().reset(reset_by="test_cleanup")


def test_cn_removed_from_rotation():
    from configs.pipeline_config import pipeline_config

    assert "CN" not in pipeline_config.MARKET_ROTATION
    assert pipeline_config.EXECUTION_MODE in ("paper", "live")


class _DummyTiger:
    def is_connected(self):
        return False
