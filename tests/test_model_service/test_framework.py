"""tests/test_model_service/test_framework.py – Tests for WalkForward, TimeSeriesCV, EarlyStopping."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from services.model_train_service.framework.walk_forward import WalkForwardValidator
from services.model_train_service.framework.timeseries_cv import (
    PurgedTimeSeriesCV,
    PurgedGroupTimeSeriesSplit,
)
from services.model_train_service.framework.early_stopping import (
    EarlyStopping,
    EarlyStoppingWrapper,
)


class TestWalkForward:
    """Tests for WalkForwardValidator."""

    @pytest.fixture
    def df(self) -> pd.DataFrame:
        dates = pd.date_range("2020-01-01", periods=1000, freq="B")
        return pd.DataFrame({
            "feature_a": np.random.randn(1000),
            "feature_b": np.random.randn(1000),
            "target": np.random.randn(1000),
        }, index=dates)

    def test_generate_splits(self, df: pd.DataFrame):
        wf = WalkForwardValidator(
            train_window=252, val_window=63, test_window=63, step_size=90,
        )
        splits = wf.generate_splits(df)
        assert len(splits) > 0
        for split in splits:
            assert "train" in split
            assert "val" in split
            assert "test" in split

    def test_time_order_enforced(self, df: pd.DataFrame):
        wf = WalkForwardValidator(train_window=252, val_window=63, test_window=63, step_size=90)
        splits = wf.generate_splits(df)
        for split in splits:
            train_end = split["train"].index.max()
            val_start = split["val"].index.min()
            val_end = split["val"].index.max()
            test_start = split["test"].index.min()

            assert train_end < val_start, "Train must end before validation starts"
            assert val_end < test_start, "Validation must end before test starts"

    def test_insufficient_data(self):
        dates = pd.date_range("2024-01-01", periods=10, freq="B")
        df = pd.DataFrame({"a": range(10)}, index=dates)
        wf = WalkForwardValidator(train_window=252)
        splits = wf.generate_splits(df)
        assert len(splits) == 0


class TestPurgedTimeSeriesCV:
    """Tests for purged time-series CV."""

    def test_split_respects_purge(self):
        dates = pd.date_range("2020-01-01", periods=500, freq="B")
        X = pd.DataFrame({"a": range(500)}, index=dates)
        cv = PurgedTimeSeriesCV(n_splits=5, purge_days=5, embargo_days=10)
        splits = list(cv.split(X))
        assert len(splits) > 0

    def test_no_overlap(self):
        dates = pd.date_range("2020-01-01", periods=500, freq="B")
        X = pd.DataFrame({"a": range(500)}, index=dates)
        cv = PurgedTimeSeriesCV(n_splits=5, purge_days=5, embargo_days=10)

        for train_idx, val_idx in cv.split(X):
            overlap = set(train_idx) & set(val_idx)
            assert len(overlap) == 0, "Train and validation indices must not overlap"


class TestEarlyStopping:
    """Tests for EarlyStopping."""

    def test_stops_after_patience(self):
        stopper = EarlyStopping(patience=3, mode="min", min_delta=0.01)

        # Decreasing losses (improving)
        assert not stopper.update(0.5, 1)
        assert not stopper.update(0.4, 2)
        assert not stopper.update(0.3, 3)

        # Plateau
        assert not stopper.update(0.35, 4)
        assert not stopper.update(0.35, 5)
        assert not stopper.update(0.35, 6)

        # Should stop at 4th plateau epoch
        assert stopper.update(0.35, 7)
        assert stopper.should_stop

    def test_max_mode(self):
        stopper = EarlyStopping(patience=2, mode="max", min_delta=0.01)
        assert not stopper.update(0.5, 1)
        assert not stopper.update(0.6, 2)
        # Drops
        assert not stopper.update(0.55, 3)
        assert not stopper.update(0.54, 4)
        assert stopper.update(0.53, 5)

    def test_reset(self):
        stopper = EarlyStopping(patience=3)
        stopper.update(0.3, 1)
        stopper.update(0.3, 2)
        stopper.update(0.3, 3)
        stopper.reset()
        assert not stopper.should_stop
        assert stopper.best_score == float("inf")
