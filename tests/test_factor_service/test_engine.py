"""tests/test_factor_service/test_engine.py – Tests for FactorEngine and FactorBase."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from services.factor_service.engine.factor_base import FactorBase
from services.factor_service.engine.factor_engine import FactorEngine
from shared.core.exceptions import FactorNotFoundError


class MockFactor(FactorBase):
    """Simple factor for testing."""
    factor_id = "TEST001"
    name = "test_close"
    category = "technical"
    subcategory = "momentum"

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return df["close"]


class MockFactor2(FactorBase):
    """Another test factor."""
    factor_id = "TEST002"
    name = "test_return"
    category = "technical"
    subcategory = "momentum"

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return df["close"].pct_change()


class TestFactorBase:
    """Tests for FactorBase."""

    def test_validate_input_required_columns(self):
        factor = MockFactor()
        df = pd.DataFrame({"close": [100, 101], "volume": [1000, 2000]})
        factor.validate_input(df)  # Should not raise

    def test_validate_input_missing_columns(self):
        factor = MockFactor()
        df = pd.DataFrame({"open": [100, 101]})
        with pytest.raises(ValueError, match="requires columns"):
            factor.validate_input(df)

    def test_to_dict(self):
        factor = MockFactor()
        d = factor.to_dict()
        assert d["id"] == "TEST001"
        assert d["name"] == "test_close"
        assert d["category"] == "technical"


class TestFactorEngine:
    """Tests for FactorEngine."""

    @pytest.fixture
    def engine(self) -> FactorEngine:
        eng = FactorEngine()
        eng.register(MockFactor())
        eng.register(MockFactor2())
        return eng

    @pytest.fixture
    def sample_df(self) -> pd.DataFrame:
        dates = pd.date_range("2024-01-01", periods=100, freq="B")
        return pd.DataFrame({
            "open": np.random.randn(100).cumsum() + 100,
            "high": np.random.randn(100).cumsum() + 102,
            "low": np.random.randn(100).cumsum() + 98,
            "close": np.random.randn(100).cumsum() + 100,
            "adj_close": np.random.randn(100).cumsum() + 100,
            "volume": np.random.randint(1000000, 50000000, 100),
        }, index=dates)

    def test_get_factor(self, engine: FactorEngine):
        factor = engine.get("TEST001")
        assert factor.factor_id == "TEST001"

    def test_get_missing_factor(self, engine: FactorEngine):
        with pytest.raises(FactorNotFoundError):
            engine.get("NONEXISTENT")

    def test_compute_single_factor(self, engine: FactorEngine, sample_df: pd.DataFrame):
        result = engine.compute(sample_df, "TEST001")
        pd.testing.assert_series_equal(result, sample_df["close"], check_names=False)

    def test_compute_all(self, engine: FactorEngine, sample_df: pd.DataFrame):
        result_df = engine.compute_all(sample_df, ["TEST001", "TEST002"])
        assert "TEST001" in result_df.columns
        assert "TEST002" in result_df.columns

    def test_winsorize(self, engine: FactorEngine):
        series = pd.Series([1, 2, 3, 4, 5, 100, -100])
        result = engine.winsorize(series, pct=0.2)
        assert result.max() < 100
        assert result.min() > -100

    def test_normalize_cross_sectional(self, engine: FactorEngine):
        series = pd.Series([1, 2, 3, 4, 5])
        result = engine.normalize_cross_sectional(series)
        assert abs(result.mean()) < 0.01
        assert 0.9 < result.std() < 1.1
