"""tests/test_data_service/test_pipeline.py – Tests for data cleansing/normalization/aggregation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from services.data_service.pipeline.cleanser import DataCleanser
from services.data_service.pipeline.normalizer import DataNormalizer, NormMode
from services.data_service.pipeline.aggregator import DataAggregator, AggFrequency


class TestDataCleanser:
    """Tests for DataCleanser."""

    @pytest.fixture
    def cleanser(self) -> DataCleanser:
        return DataCleanser(zscore_threshold=4.0, max_missing_pct=0.3, min_bar_count=10)

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

    def test_clean_fills_missing_values(self, cleanser: DataCleanser, sample_df: pd.DataFrame):
        df = sample_df.copy()
        df.loc[df.index[50:55], "close"] = np.nan
        result = cleanser.clean(df, "TEST")
        assert result["close"].isna().sum() == 0

    def test_clean_detects_outliers(self, cleanser: DataCleanser, sample_df: pd.DataFrame):
        df = sample_df.copy()
        df.loc[df.index[20], "close"] = 999999.0  # Massive outlier
        result = cleanser.clean(df, "TEST")
        assert result.loc[df.index[20], "close"] < 999999.0

    def test_quality_score_range(self, cleanser: DataCleanser, sample_df: pd.DataFrame):
        score = cleanser.compute_quality_score(sample_df)
        assert 0.0 <= score <= 1.0

    def test_rejects_insufficient_data(self, cleanser: DataCleanser):
        df = pd.DataFrame({"open": [100], "close": [100], "volume": [1000]})
        cleanser.min_bar_count = 50
        with pytest.raises(ValueError, match="Insufficient data"):
            cleanser.clean(df, "SPARSE")


class TestDataNormalizer:
    """Tests for DataNormalizer."""

    @pytest.fixture
    def sample_df(self) -> pd.DataFrame:
        dates = pd.date_range("2024-01-01", periods=100, freq="B")
        return pd.DataFrame({
            "close": np.random.randn(100).cumsum() + 100,
            "volume": np.random.randint(1000000, 50000000, 100).astype(float),
        }, index=dates)

    def test_zscore_normalization(self, sample_df: pd.DataFrame):
        norm = DataNormalizer(mode=NormMode.ZSCORE)
        result = norm.fit_transform(sample_df)
        assert abs(result["close"].mean()) < 0.1
        assert 0.9 < result["close"].std() < 1.1

    def test_minmax_normalization(self, sample_df: pd.DataFrame):
        norm = DataNormalizer(mode=NormMode.MINMAX)
        result = norm.fit_transform(sample_df)
        assert result["close"].min() >= 0.0
        assert result["close"].max() <= 1.0

    def test_inverse_transform(self, sample_df: pd.DataFrame):
        norm = DataNormalizer(mode=NormMode.ZSCORE)
        normalized = norm.fit_transform(sample_df)
        restored = norm.inverse_transform(normalized)
        pd.testing.assert_series_equal(
            sample_df["close"].round(6),
            restored["close"].round(6),
            check_names=False,
        )


class TestDataAggregator:
    """Tests for DataAggregator."""

    @pytest.fixture
    def daily_df(self) -> pd.DataFrame:
        dates = pd.date_range("2024-01-01", periods=252, freq="B")
        np.random.seed(42)
        return pd.DataFrame({
            "open": np.random.randn(252).cumsum() + 100,
            "high": np.random.randn(252).cumsum() + 102,
            "low": np.random.randn(252).cumsum() + 98,
            "close": np.random.randn(252).cumsum() + 100,
            "adj_close": np.random.randn(252).cumsum() + 100,
            "volume": np.random.randint(1000000, 50000000, 252),
        }, index=dates)

    def test_daily_to_weekly(self, daily_df: pd.DataFrame):
        result = DataAggregator.daily_to_weekly(daily_df)
        assert len(result) < len(daily_df)
        assert "open" in result.columns

    def test_daily_to_monthly(self, daily_df: pd.DataFrame):
        result = DataAggregator.daily_to_monthly(daily_df)
        assert len(result) < 30

    def test_compute_returns(self, daily_df: pd.DataFrame):
        result = DataAggregator.compute_returns(daily_df, periods=[1, 5, 21])
        assert "ret_1d" in result.columns
        assert "ret_5d" in result.columns
        assert "ret_21d" in result.columns
