"""services/model_train_service/framework/walk_forward.py – Walk-Forward validation.

Strict time-order cross-validation for financial time series.
Splits: [train_start, val_start) → [val_start, test_start) → [test_start, end)
Rolling window, step=90 days, train_window=252 days.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

import numpy as np
import pandas as pd
from loguru import logger

from services.model_train_service.config import train_config


class WalkForwardValidator:
    """Walk-forward cross-validator for time-series ML.

    Generates train/val/test splits with strict temporal ordering.
    No future information leakage.

    Attributes:
        train_window: Training window in trading days (default 252).
        val_window: Validation window in calendar days (default 63).
        test_window: Test window in calendar days (default 63).
        step_size: Roll-forward step in calendar days (default 90).
        min_train_size: Minimum training observations.
    """

    def __init__(
        self,
        train_window: int | None = None,
        val_window: int | None = None,
        test_window: int | None = None,
        step_size: int | None = None,
        min_train_size: int = 100,
    ) -> None:
        self.train_window = train_window or train_config.TRAIN_WINDOW_DAYS
        self.val_window = val_window or train_config.VALID_WINDOW_DAYS
        self.test_window = test_window or train_config.TEST_WINDOW_DAYS
        self.step_size = step_size or train_config.WALK_FORWARD_STEP_DAYS
        self.min_train_size = min_train_size

    def generate_splits(
        self,
        df: pd.DataFrame,
        date_col: str | None = None,
    ) -> list[dict[str, pd.DataFrame]]:
        """Generate walk-forward splits from a DataFrame.

        Args:
            df: DataFrame with a DatetimeIndex (or date_col column).
            date_col: Name of date column if index is not datetime.

        Returns:
            List of dicts with 'train', 'val', 'test' DataFrames.
        """
        if date_col and date_col in df.columns:
            dates = pd.to_datetime(df[date_col])
        elif isinstance(df.index, pd.DatetimeIndex):
            dates = df.index
        elif isinstance(df.index, pd.MultiIndex):
            dates = df.index.get_level_values("date") if "date" in df.index.names else df.index.get_level_values(0)
        else:
            # Assume sequential; generate pseudo-dates
            dates = pd.date_range("2020-01-01", periods=len(df), freq="B")
            df = df.copy()
            df.index = dates

        all_dates = sorted(pd.Series(pd.to_datetime(dates)).unique())
        total_days = (all_dates[-1] - all_dates[0]).days

        if total_days < self.train_window + self.val_window + self.test_window:
            logger.warning(
                f"Insufficient date range: {total_days}d < "
                f"{self.train_window + self.val_window + self.test_window}d"
            )
            return []

        current_start = all_dates[0]
        splits: list[dict[str, pd.DataFrame]] = []

        while True:
            train_end = current_start + timedelta(days=self.train_window)
            val_end = train_end + timedelta(days=self.val_window)
            test_end = val_end + timedelta(days=self.test_window)

            if test_end > all_dates[-1]:
                break

            train_dates = [d for d in all_dates if current_start <= d < train_end]
            val_dates = [d for d in all_dates if train_end <= d < val_end]
            test_dates = [d for d in all_dates if val_end <= d < test_end]

            def _filter(date_list: list) -> pd.DataFrame:
                if isinstance(df.index, pd.DatetimeIndex):
                    return df.loc[df.index.isin(date_list)]
                return df.loc[dates.isin(date_list)]

            train_df = _filter(train_dates)
            val_df = _filter(val_dates)
            test_df = _filter(test_dates)

            if len(train_df) >= self.min_train_size and len(val_df) > 0 and len(test_df) > 0:
                splits.append({"train": train_df, "val": val_df, "test": test_df})

            current_start += timedelta(days=self.step_size)

        logger.info(f"Walk-forward: generated {len(splits)} splits")
        return splits

    def run(
        self,
        df: pd.DataFrame,
        train_fn: Any,  # Callable[[pd.DataFrame, pd.DataFrame, pd.DataFrame], dict[str, float]]
        date_col: str | None = None,
    ) -> list[dict[str, Any]]:
        """Run walk-forward training across all splits.

        Args:
            df: Full dataset.
            train_fn: Function(split) → metrics dict.
            date_col: Date column if needed.

        Returns:
            List of per-split results with metrics.
        """
        splits = self.generate_splits(df, date_col)
        results: list[dict[str, Any]] = []

        for i, split in enumerate(splits):
            metrics = train_fn(split["train"], split["val"], split["test"])
            split_result = {
                "fold": i,
                "train_size": len(split["train"]),
                "val_size": len(split["val"]),
                "test_size": len(split["test"]),
                "train_start": str(split["train"].index[0])[:10],
                "train_end": str(split["train"].index[-1])[:10],
                **metrics,
            }
            results.append(split_result)
            logger.info(f"Fold {i}: train_loss={metrics.get('val_loss', 'N/A')}")

        # Aggregate statistics
        agg_metrics: dict[str, float] = {}
        for key in results[0].keys():
            values = [r[key] for r in results if isinstance(r.get(key), (int, float))]
            if values:
                agg_metrics[f"mean_{key}"] = round(float(np.mean(values)), 6)
                agg_metrics[f"std_{key}"] = round(float(np.std(values)), 6)

        logger.info(f"Walk-forward aggregate: {agg_metrics}")
        return results
