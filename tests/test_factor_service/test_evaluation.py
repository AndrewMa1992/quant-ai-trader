"""tests/test_factor_service/test_evaluation.py – Tests for factor evaluation modules."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from services.factor_service.evaluation.ic_analysis import ICAnalyzer
from services.factor_service.evaluation.correlation import FactorCorrelation
from services.factor_service.evaluation.decay import DecayAnalyzer
from services.factor_service.evaluation.stratification import StratificationAnalyzer
from services.factor_service.evaluation.fama_macbeth import FamaMacBeth


class TestICAnalysis:
    """Tests for ICAnalyzer."""

    @pytest.fixture
    def analyzer(self) -> ICAnalyzer:
        return ICAnalyzer(rolling_window=63)

    def test_compute_ic(self, analyzer: ICAnalyzer):
        np.random.seed(42)
        dates = pd.date_range("2022-01-01", periods=500, freq="B")
        factor = pd.Series(np.random.randn(500), index=dates)
        returns = pd.Series(np.random.randn(500), index=dates, name="ret")

        result = analyzer.compute_ic(factor, returns)
        assert "rank_ic_mean" in result
        assert "information_ratio" in result
        assert isinstance(result["ic_series"], list)

    def test_insufficient_data(self, analyzer: ICAnalyzer):
        dates = pd.date_range("2024-01-01", periods=10, freq="B")
        factor = pd.Series(np.random.randn(10), index=dates)
        returns = pd.Series(np.random.randn(10), index=dates)
        result = analyzer.compute_ic(factor, returns)
        assert np.isnan(result["rank_ic_mean"])


class TestFactorCorrelation:
    """Tests for FactorCorrelation."""

    def test_correlation_matrix(self):
        np.random.seed(42)
        corr_analyzer = FactorCorrelation(threshold=0.7)
        df = pd.DataFrame({
            "f1": np.random.randn(100),
            "f2": np.random.randn(100),
            "f3": np.random.randn(100),
        })
        matrix, redundant = corr_analyzer.compute_correlation_matrix(df)
        assert matrix.shape == (3, 3)

    def test_detect_redundant_high_corr(self):
        corr_analyzer = FactorCorrelation(threshold=0.5)
        df = pd.DataFrame({
            "f1": np.arange(100),
            "f2": np.arange(100) * 0.9 + np.random.randn(100) * 0.1,  # Highly correlated
        })
        matrix, redundant = corr_analyzer.compute_correlation_matrix(df)
        assert len(redundant) >= 1


class TestDecayAnalysis:
    """Tests for DecayAnalyzer."""

    def test_decay_curve(self):
        np.random.seed(42)
        analyzer = DecayAnalyzer(max_lags=10)
        dates = pd.date_range("2022-01-01", periods=500, freq="B")
        factor = pd.Series(np.random.randn(500).cumsum() * 0.01, index=dates)
        returns = pd.Series(np.random.randn(500) * 0.01, index=dates)

        result = analyzer.analyze(factor, returns)
        assert "half_life" in result
        assert len(result["decay_curve"]) == 10


class TestStratification:
    """Tests for StratificationAnalyzer."""

    def test_stratify(self):
        np.random.seed(42)
        analyzer = StratificationAnalyzer(n_quantiles=5, horizon="21d")

        factor = pd.Series(np.random.randn(200), name="factor")
        forward_returns = pd.Series(np.random.randn(200) * 0.01, index=factor.index)

        result = analyzer.analyze(factor, forward_returns)
        assert "spread" in result
        assert len(result["groups"]) > 0


class TestFamaMacBeth:
    """Tests for FamaMacBeth."""

    def test_single_factor(self):
        np.random.seed(42)
        fm = FamaMacBeth(min_obs_per_period=5, min_periods=10)

        dates = pd.date_range("2022-01-01", periods=100, freq="B")
        assets = [f"A{i}" for i in range(20)]
        returns = pd.DataFrame(np.random.randn(100, 20) * 0.01, index=dates, columns=assets)
        factors = pd.DataFrame(np.random.randn(100, 20), index=dates, columns=assets)

        result = fm.run(returns, factors)
        if "error" not in result:
            assert "coefficients" in result
            assert "alpha" in result["coefficients"] or "factor" in result["coefficients"]

    def test_insufficient_data(self):
        fm = FamaMacBeth(min_periods=1000)
        dates = pd.date_range("2024-01-01", periods=5, freq="B")
        returns = pd.DataFrame(np.random.randn(5, 3), index=dates)
        factors = pd.DataFrame(np.random.randn(5, 3), index=dates, columns=returns.columns)

        result = fm.run(returns, factors)
        assert "error" in result
