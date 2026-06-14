"""tests/test_risk_service/test_barra.py – Tests for Barra risk model components."""

from __future__ import annotations

import numpy as np
import pytest

from services.risk_service.barra.factor_exposure import BarraExposureCalculator
from services.risk_service.barra.covariance import CovarianceEstimator
from services.risk_service.barra.specific_risk import SpecificRiskEstimator


class TestBarraExposure:
    """Tests for BarraExposureCalculator."""

    def test_all_nine_factors_returned(self):
        calc = BarraExposureCalculator()
        exposures = calc.compute_exposures("AAPL")
        assert len(exposures) == 9
        for factor in BarraExposureCalculator.FACTOR_NAMES:
            assert factor in exposures

    def test_nonexistent_ticker_zeros(self):
        calc = BarraExposureCalculator()
        exposures = calc.compute_exposures("TICKER_THAT_DOES_NOT_EXIST_XYZ")
        assert all(v == 0.0 for v in exposures.values())


class TestCovarianceEstimator:
    """Tests for CovarianceEstimator."""

    def test_compute_returns_matrix(self):
        cov = CovarianceEstimator(halflife=60)
        # Use tickers that likely have data
        matrix = cov.compute(["SPY", "QQQ"])
        assert matrix.shape == (2, 2)
        assert np.all(np.diag(matrix) > 0)

    def test_correlation_from_covariance(self):
        cov = CovarianceEstimator()
        matrix = cov.compute(["SPY", "QQQ"])
        corr = cov.compute_correlation_from_covariance(matrix)
        assert -1.0 <= corr[0, 1] <= 1.0

    def test_eigenvalue_adjustment_positive_definite(self):
        cov = CovarianceEstimator(eigenvalue_floor=1e-6)
        matrix = cov.compute(["SPY", "QQQ"])
        eigvals = np.linalg.eigvalsh(matrix)
        assert np.all(eigvals >= cov.eigenvalue_floor)


class TestSpecificRiskEstimator:
    """Tests for SpecificRiskEstimator."""

    def test_estimate_returns_metrics(self):
        est = SpecificRiskEstimator()
        result = est.estimate("AAPL")
        assert "specific_risk" in result
        assert "systematic_risk" in result
        assert "total_risk" in result
        assert "r_squared" in result

    def test_specific_risk_nonnegative(self):
        est = SpecificRiskEstimator()
        result = est.estimate("AAPL")
        assert result["specific_risk"] >= 0
