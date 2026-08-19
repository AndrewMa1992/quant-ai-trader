"""Institutional controls: kill switch, live promotion, exposure gate, TCA."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def tmp_kill_switch(tmp_path, monkeypatch):
    from shared import kill_switch as ks_mod

    path = tmp_path / "kill_switch.json"
    monkeypatch.setattr(ks_mod, "_GLOBAL", None)
    switch = ks_mod.KillSwitch(path)
    monkeypatch.setattr(ks_mod, "_GLOBAL", switch)
    return switch


@pytest.fixture()
def tmp_live_gate(tmp_path, monkeypatch):
    from shared import live_promotion as lp

    path = tmp_path / "live_promotion.json"
    monkeypatch.setattr(lp, "_GATE_PATH", path)
    return path


def test_kill_switch_persists(tmp_kill_switch, tmp_path):
    from shared.kill_switch import KillSwitch

    tmp_kill_switch.engage("test halt", engaged_by="unit")
    assert tmp_kill_switch.engaged is True
    reloaded = KillSwitch(tmp_kill_switch.path)
    assert reloaded.engaged is True
    assert "test halt" in reloaded.status()["reason"]
    tmp_kill_switch.reset(reset_by="unit")
    assert tmp_kill_switch.engaged is False


@pytest.mark.asyncio
async def test_risk_gate_blocks_on_kill_switch(tmp_kill_switch, monkeypatch):
    from configs import pipeline_config as pc
    from shared.risk_gate import RiskGate

    monkeypatch.setattr(pc.pipeline_config, "EXECUTION_MODE", "paper")
    monkeypatch.setattr(pc.pipeline_config, "ENABLE_RISK_CHECKS", True)
    tmp_kill_switch.engage("halt", engaged_by="test")

    class _CB:
        def allow_order(self, *a, **k):
            return True

    gate = RiskGate(circuit_breaker=_CB(), risk_service_url="http://localhost:8015")
    result = await gate.check(
        "AAPL",
        10,
        100.0,
        {"total_value": 100_000, "positions": {}, "position_values": {}},
        0.5,
    )
    assert result.passed is False
    assert "KillSwitch" in result.reason


def test_exposure_gate_rejects_concentrated_name(monkeypatch):
    from configs import pipeline_config as pc
    from shared.risk_gate import RiskGate

    monkeypatch.setattr(pc.pipeline_config, "ENABLE_RISK_CHECKS", True)
    gate = RiskGate(circuit_breaker=_CB(), risk_service_url="http://localhost:8015")
    # Projected AAPL weight after buy ≈ 25k/100k = 25% > 15% single-name
    result = gate._check_exposures(
        "AAPL",
        100,
        250.0,
        {
            "total_value": 100_000.0,
            "position_values": {"AAPL": 0.0},
        },
    )
    assert result["passed"] is False
    assert "AAPL" in result["reason"]


def test_live_promotion_requires_checklist(tmp_live_gate, monkeypatch):
    monkeypatch.setenv("QAT_TRADING_SIMULATION_MODE", "false")
    monkeypatch.setenv("QAT_EXECUTION_MODE", "live")
    # Clear cached modules that read env at import time paths
    from shared import live_promotion as lp
    from shared.execution_mode import is_simulation_mode

    assert is_simulation_mode() is False

    with pytest.raises(ValueError):
        lp.approve_live("ops", {"operator_ack": True})

    checklist = {k: True for k in lp.REQUIRED_CHECKS}
    data = lp.approve_live("ops", checklist)
    assert data["approved"] is True
    assert lp.can_place_live_orders() is True

    lp.revoke_live("ops", "done")
    assert lp.can_place_live_orders() is False


def test_simulation_lock_blocks_live(tmp_live_gate, monkeypatch):
    from shared import live_promotion as lp

    monkeypatch.setenv("QAT_TRADING_SIMULATION_MODE", "true")
    monkeypatch.setenv("QAT_EXECUTION_MODE", "live")
    checklist = {k: True for k in lp.REQUIRED_CHECKS}
    with pytest.raises(ValueError, match="SIMULATION"):
        lp.approve_live("ops", checklist)


def test_tca_slippage_and_participation():
    from services.execution_service.live.tca import analyze_fill, pre_trade_participation_ok

    ok, _ = pre_trade_participation_ok(1_000, 100_000)
    assert ok is True
    bad, msg = pre_trade_participation_ok(10_000, 100_000)
    assert bad is False
    assert "participation" in msg

    # Buy fill above arrival → positive slippage
    r = analyze_fill("AAPL", "buy", 10, arrival_price=100.0, fill_price=101.0)
    assert r.slippage_bps == pytest.approx(100.0, abs=0.1)
    assert r.passed is False  # > MAX_SLIPPAGE_BPS (10)


def test_risk_manager_limits_from_risk_limits():
    from configs.risk_limits import RISK_LIMITS
    from shared import risk_manager as rm_mod

    assert rm_mod.DAILY_LOSS_LIMIT == RISK_LIMITS.DAILY_LOSS_LIMIT
    assert rm_mod.MAX_DRAWDOWN == RISK_LIMITS.MAX_DRAWDOWN_PORTFOLIO
    assert rm_mod.MAX_POSITION_SIZE == RISK_LIMITS.MAX_POSITION_SIZE


def test_risk_manager_kill_switch_blocks(tmp_kill_switch):
    from shared.risk_manager import RiskManager

    rm = RiskManager(initial_capital=100_000)
    tmp_kill_switch.engage("desk halt", engaged_by="test")
    report = rm.check_circuit_breaker()
    assert report.passed is False
    assert report.circuit_breaker is True
    assert "Kill switch" in report.reason or "Kill" in report.reason


def test_audit_trail_writes(tmp_path, monkeypatch):
    from shared.audit_trail import AuditTrail

    trail = AuditTrail(tmp_path)
    trail.risk_reject("AAPL", "VaR breach", {"var": 0.05})
    trail.cycle(1, "2026-08-18", orders=2, approved=1, rejected=1)
    files = list(tmp_path.glob("*.jsonl"))
    assert files
    content = files[0].read_text(encoding="utf-8")
    assert "AAPL" in content or "cycle" in content


def test_execution_mode_defaults_paper(monkeypatch):
    monkeypatch.setenv("QAT_TRADING_SIMULATION_MODE", "true")
    monkeypatch.setenv("QAT_EXECUTION_MODE", "live")
    from shared.execution_mode import get_execution_mode, is_live_execution

    assert get_execution_mode() == "paper"
    assert is_live_execution() is False


class _CB:
    def allow_order(self, *a, **k):
        return True
