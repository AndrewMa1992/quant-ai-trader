"""Tests for paper/sim mode lock and training pipeline helpers."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _ConnectedTiger:
    def is_connected(self):
        return True

    def place_order(self, **kwargs):
        self.last = kwargs
        return {"order_id": "x"}


def test_simulation_mode_forces_paper(monkeypatch):
    monkeypatch.setenv("QAT_TRADING_SIMULATION_MODE", "true")
    monkeypatch.setenv("QAT_EXECUTION_MODE", "live")
    # Re-import helpers after env change
    import importlib
    import shared.execution_mode as em

    importlib.reload(em)
    assert em.is_simulation_mode() is True
    assert em.get_execution_mode() == "paper"
    assert em.is_live_execution() is False


def test_live_requires_sim_off(monkeypatch):
    monkeypatch.setenv("QAT_TRADING_SIMULATION_MODE", "false")
    monkeypatch.setenv("QAT_EXECUTION_MODE", "live")
    import importlib
    import shared.execution_mode as em

    importlib.reload(em)
    assert em.get_execution_mode() == "live"
    assert em.can_place_live_order(_ConnectedTiger()) is True


def test_liquidate_paper_does_not_place_order(monkeypatch):
    monkeypatch.setenv("QAT_TRADING_SIMULATION_MODE", "true")
    monkeypatch.setenv("QAT_EXECUTION_MODE", "paper")
    import importlib
    import shared.execution_mode as em
    import shared.risk_manager as rm

    importlib.reload(em)
    importlib.reload(rm)

    tiger = _ConnectedTiger()
    risk = rm.RiskManager(initial_capital=100_000)
    risk.update_portfolio_state(110_000, 10_000, {"AAPL": 10}, {"AAPL": 100.0})
    records = risk.liquidate_all({"AAPL": 100.0}, tiger)
    assert len(records) == 1
    assert not hasattr(tiger, "last"), "paper mode must not call tiger.place_order"


def test_train_request_normalizes_rl_agent():
    from services.model_train_service.api.schemas import TrainRequest

    req = TrainRequest(model_type="rl_agent", tickers=["AAPL"], start_date="2023-01-01", end_date="2024-01-01")
    assert req.model_type == "rl"


def test_pipeline_config_forced_paper(monkeypatch):
    monkeypatch.setenv("QAT_TRADING_SIMULATION_MODE", "true")
    monkeypatch.setenv("QAT_EXECUTION_MODE", "live")
    from configs.pipeline_config import PipelineConfig

    cfg = PipelineConfig()
    assert cfg.EXECUTION_MODE == "paper"


def test_data_dir_unified():
    from services.data_service.config import data_config

    assert "cache/market_data" not in data_config.DATA_DIR or data_config.DATA_DIR.endswith("data")
    # Prefer ./data as unified root
    assert data_config.DATA_DIR in ("./data", "data") or data_config.DATA_DIR.endswith("/data")
