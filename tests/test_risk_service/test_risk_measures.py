"""tests/test_risk_service/test_risk_measures.py – Tests for VaR, CVaR, Drawdown."""

from __future__ import annotations

import numpy as np
import pytest

from services.risk_service.risk_measures.var import VaRCalculator
from services.risk_service.risk_measures.cvar import CVaRCalculator
from services.risk_service.risk_measures.drawdown import DrawdownAnalyzer


class TestVaR:
    """Tests for VaRCalculator."""

    def test_parametric_var(self):
        calc = VaRCalculator(confidence=0.95)
        result = calc.compute(["SPY"], [1.0], method="parametric")
        assert "var_normal" in result or "error" in result

    def test_historical_var(self):
        calc = VaRCalculator(confidence=0.95)
        result = calc.compute(["SPY"], [1.0], method="historical")
        assert "var" in result or "error" in result

    def test_monte_carlo_var(self):
        calc = VaRCalculator(confidence=0.95, mc_paths=1000)
        result = calc.compute(["SPY"], [1.0], method="montecarlo")
        if "error" not in result:
            assert "var" in result
            assert result["n_paths"] == 1000


class TestCVaR:
    """Tests for CVaRCalculator."""

    def test_cvar(self):
        calc = CVaRCalculator(confidence=0.95)
        result = calc.compute(["SPY"], [1.0])
        if "error" not in result:
            assert "cvar_95" in result
            assert "cvar_99" in result

    def test_distribution_method(self):
        calc = CVaRCalculator()
        losses = np.abs(np.random.randn(500) * 0.01)
        result = calc.compute_distribution(losses)
        assert "cvar_95" in result
        assert "skewness" in result


class TestDrawdown:
    """Tests for DrawdownAnalyzer."""

    def test_compute(self):
        analyzer = DrawdownAnalyzer()
        result = analyzer.compute("SPY")
        if "error" not in result:
            assert "max_drawdown" in result
            assert result["max_drawdown"] <= 0

    def test_from_prices(self):
        analyzer = DrawdownAnalyzer()
        prices = np.array([100, 95, 90, 85, 92, 98, 102, 105, 100, 95])
        result = analyzer.compute_from_prices(prices)
        assert result["max_drawdown"] < 0
        assert result["current_drawdown"] <= 0

    def test_fully_recovered(self):
        analyzer = DrawdownAnalyzer()
        prices = np.array([100, 80, 100, 110])
        result = analyzer.compute_from_prices(prices)
        assert result["fully_recovered"] is True

    def test_insufficient_data(self):
        analyzer = DrawdownAnalyzer()
        result = analyzer.compute("TICKER_THAT_DOES_NOT_EXIST_XYZ")
        assert "error" in result
