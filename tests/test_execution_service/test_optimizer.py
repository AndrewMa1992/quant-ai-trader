"""tests/test_execution_service/test_optimizer.py – Tests for portfolio optimizers."""

from __future__ import annotations

import numpy as np
import pytest

from services.execution_service.optimizer.markowitz import MarkowitzOptimizer
from services.execution_service.optimizer.black_litterman import BlackLittermanOptimizer
from services.execution_service.optimizer.risk_parity import RiskParityOptimizer
from services.execution_service.optimizer.constraints import ConstraintSystem


class TestMarkowitz:
    """Tests for MarkowitzOptimizer."""

    def test_max_sharpe(self):
        opt = MarkowitzOptimizer(objective="max_sharpe")
        result = opt.optimize(["SPY", "QQQ"])
        assert "weights" in result
        assert len(result["weights"]) == 2
        assert abs(sum(result["weights"].values()) - 1.0) < 0.01

    def test_min_risk(self):
        opt = MarkowitzOptimizer(objective="min_risk")
        result = opt.optimize(["SPY", "QQQ", "IWM"])
        assert len(result["weights"]) == 3

    def test_fallback_equal_weight(self):
        opt = MarkowitzOptimizer()
        result = opt._fallback_equal_weight(["SPY", "QQQ", "IWM", "GLD"])
        assert result["weights"]["SPY"] == pytest.approx(0.25, abs=0.01)


class TestBlackLitterman:
    """Tests for BlackLittermanOptimizer."""

    def test_no_views(self):
        opt = BlackLittermanOptimizer()
        result = opt.optimize(["SPY", "QQQ"], views=[])
        assert "weights" in result

    def test_with_view(self):
        opt = BlackLittermanOptimizer()
        views = [{"ticker": "QQQ", "return": 0.15, "confidence": 0.8}]
        result = opt.optimize(["SPY", "QQQ"], views=views)
        assert result.get("n_views", 0) == 1

    def test_relative_view(self):
        opt = BlackLittermanOptimizer()
        views = [{"ticker_a": "QQQ", "ticker_b": "SPY", "outperformance": 0.10, "confidence": 0.7}]
        result = opt.optimize(["SPY", "QQQ"], views=views)
        assert "weights" in result


class TestRiskParity:
    """Tests for RiskParityOptimizer."""

    def test_optimize(self):
        opt = RiskParityOptimizer(max_iter=50)
        result = opt.optimize(["SPY", "QQQ", "IWM"])
        assert "weights" in result
        assert "risk_contributions" in result
        assert len(result["weights"]) == 3


class TestConstraintSystem:
    """Tests for ConstraintSystem."""

    def test_validate_valid_weights(self):
        cs = ConstraintSystem()
        result = cs.validate_weights({"AAPL": 0.08, "MSFT": 0.08})
        assert result["valid"] is True

    def test_validate_max_weight(self):
        cs = ConstraintSystem(config={"max_weight": 0.10})
        result = cs.validate_weights({"AAPL": 0.15, "MSFT": 0.08})
        assert result["valid"] is False

    def test_sanitize_clips_to_max(self):
        cs = ConstraintSystem(config={"max_weight": 0.10})
        sanitized = cs.sanitize_weights({"AAPL": 0.20, "MSFT": 0.05})
        assert sanitized["AAPL"] <= 0.10
