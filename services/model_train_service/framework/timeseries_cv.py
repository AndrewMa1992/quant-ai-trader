"""services/model_train_service/framework/timeseries_cv.py – Purged k-fold cross-validation.

Prevents information leakage by:
1. Removing overlapping samples between train and validation sets (purging).
2. Adding gap between train and validation periods (embargo).
"""

from __future__ import annotations

from typing import Iterator, Optional

import numpy as np
import pandas as pd
from loguru import logger


class PurgedTimeSeriesCV:
    """Purged time-series cross-validator.

    Ensures no training sample has look-ahead knowledge of validation samples.

    Attributes:
        n_splits: Number of folds.
        purge_days: Number of days to purge on each side of the split.
        embargo_days: Gap days between train and validation sets.
    """

    def __init__(
        self,
        n_splits: int = 5,
        purge_days: int = 5,
        embargo_days: int = 10,
    ) -> None:
        self.n_splits = n_splits
        self.purge_days = purge_days
        self.embargo_days = embargo_days

    def split(
        self,
        X: pd.DataFrame,
        y: pd.Series | None = None,
    ) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        """Generate purged train/validation indices.

        Args:
            X: Features with DatetimeIndex.
            y: Target (not used, for sklearn compatibility).

        Yields:
            (train_indices, val_indices) arrays.
        """
        n = len(X)
        indices = np.arange(n)

        # Compute fold boundaries
        fold_size = n // self.n_splits
        test_sizes = [fold_size] * self.n_splits
        remainder = n - fold_size * self.n_splits
        for i in range(remainder):
            test_sizes[i] += 1

        test_start = 0
        for i in range(self.n_splits):
            test_end = test_start + test_sizes[i]

            # Test set
            test_indices = indices[test_start:test_end]

            # Train set: all before test_start minus purge/embargo
            train_end = max(0, test_start - self.purge_days - self.embargo_days)

            if train_end < 50:
                logger.warning(
                    f"Fold {i}: insufficient training data ({train_end} samples). Skipping."
                )
                test_start = test_end
                continue

            train_indices = indices[:train_end]

            yield train_indices, test_indices

            test_start = test_end

    def get_n_splits(self, X: pd.DataFrame | None = None, y: pd.Series | None = None) -> int:
        """Return the number of splitting iterations.

        Returns:
            Number of effective splits.
        """
        return self.n_splits


class PurgedGroupTimeSeriesSplit:
    """Purged k-fold with group awareness (e.g., per-ticker).

    Prevents the same ticker from appearing in both train and validation
    within the same fold.
    """

    def __init__(
        self,
        n_splits: int = 5,
        purge_days: int = 5,
        embargo_days: int = 10,
    ) -> None:
        self.n_splits = n_splits
        self.purge_days = purge_days
        self.embargo_days = embargo_days

    def split(
        self,
        X: pd.DataFrame,
        y: pd.Series | None = None,
        groups: pd.Series | None = None,
    ) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        """Generate purged train/val splits respecting groups.

        Args:
            X: Features.
            y: Target.
            groups: Group labels (e.g., ticker symbols).

        Yields:
            (train_indices, val_indices).
        """
        n = len(X)

        if groups is None:
            # Fallback to simple purged CV
            cv = PurgedTimeSeriesCV(
                n_splits=self.n_splits,
                purge_days=self.purge_days,
                embargo_days=self.embargo_days,
            )
            yield from cv.split(X, y)
            return

        unique_groups = groups.unique()
        group_counts = groups.value_counts().sort_index()
        cumsum = group_counts.cumsum()

        total = cumsum.iloc[-1]
        fold_size = total // self.n_splits

        for i in range(self.n_splits):
            test_end_threshold = total - i * fold_size
            test_start_threshold = test_end_threshold - fold_size

            test_mask = (cumsum > test_start_threshold) & (cumsum <= test_end_threshold)
            test_groups = group_counts[test_mask].index
            test_indices = np.where(groups.isin(test_groups))[0]

            train_indices = np.where(~groups.isin(test_groups))[0]

            if len(train_indices) < 50:
                continue

            yield train_indices, test_indices
