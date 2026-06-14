"""services/model_train_service/data_loader.py – Unified data loader for model training.

Builds training datasets from Parquet market data + computed factors.
Outputs time-sliced X (features) / y (target) / folds for CV.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional, Tuple

import numpy as np
import pandas as pd
from loguru import logger

from services.data_service.pipeline.aggregator import DataAggregator
from services.data_service.pipeline.cleanser import DataCleanser
from services.data_service.storage.parquet_store import ParquetStore
from services.factor_service.engine.factor_engine import FactorEngine
from shared.core.exceptions import DataError


def create_dataset(
    tickers: list[str],
    start_date: str = "2023-01-01",
    end_date: str = "2024-12-31",
    horizon: int = 21,
    include_factors: bool = True,
) -> Optional[pd.DataFrame]:
    """Load OHLCV data + factors → build supervised ML dataset.

    Args:
        tickers: List of ticker symbols.
        start_date: Start date (YYYY-MM-DD).
        end_date: End date (YYYY-MM-DD).
        horizon: Forward return horizon for target (trading days).
        include_factors: Whether to compute and include factors as features.

    Returns:
        DataFrame with features + 'target' column (forward return), or None.
    """
    store = ParquetStore()
    cleanser = DataCleanser()
    engine = FactorEngine()

    frames: list[pd.DataFrame] = []
    s_date = date.fromisoformat(start_date)
    e_date = date.fromisoformat(end_date)

    for ticker in tickers:
        try:
            df = store.read_daily(ticker, s_date, e_date)
            if df is None or len(df) < 100:
                logger.warning(f"Skipping {ticker}: insufficient data ({len(df) if df is not None else 0})")
                continue

            df = cleanser.clean(df, ticker)

            # Add returns
            df = DataAggregator.compute_returns(df, periods=[1, 5, 21, 63])

            # Add factors
            if include_factors:
                try:
                    engine.register_all()
                    factor_df = engine.compute_all(df)
                    frames.append(factor_df)
                except Exception as e:
                    logger.warning(f"Factor computation failed for {ticker}: {e}")
                    frames.append(df)
            else:
                frames.append(df)

        except Exception as e:
            logger.error(f"Failed to load {ticker}: {e}")
            continue

    if not frames:
        logger.error("No data loaded for any ticker")
        return None

    combined = pd.concat(frames, keys=tickers, names=["ticker", "date"])

    # Create target: forward return over horizon
    if "adj_close" in combined.columns:
        col = "adj_close"
    elif "close" in combined.columns:
        col = "close"
    else:
        raise DataError("No close/adj_close column in dataset")

    # Forward return per ticker
    combined["target"] = combined.groupby(level="ticker")[col].transform(
        lambda x: x.pct_change(horizon).shift(-horizon)
    )

    # Drop rows with NaN target
    combined = combined.dropna(subset=["target"])

    # Remove infinite values
    combined = combined.replace([np.inf, -np.inf], np.nan)
    combined = combined.dropna()

    logger.info(f"Dataset created: {len(combined)} rows, {len(combined.columns)} columns")
    return combined


def create_time_slices(
    df: pd.DataFrame,
    train_window: int = 252,
    val_window: int = 63,
    test_window: int = 63,
    step: int = 90,
) -> list[dict[str, pd.DataFrame]]:
    """Create rolling time-slice folds for walk-forward training.

    Args:
        df: DataFrame with DatetimeIndex (second level).
        train_window: Training window in trading days.
        val_window: Validation window days.
        test_window: Test window days.
        step: Step size between folds.

    Returns:
        List of folds, each with 'train', 'val', 'test' DataFrames.
    """
    if isinstance(df.index, pd.MultiIndex):
        dates = sorted(df.index.get_level_values("date").unique())
    else:
        dates = sorted(df.index.unique())

    folds: list[dict[str, pd.DataFrame]] = []
    i = 0

    while i + train_window + val_window + test_window <= len(dates):
        train_dates = dates[i : i + train_window]
        val_dates = dates[i + train_window : i + train_window + val_window]
        test_dates = dates[i + train_window + val_window : i + train_window + val_window + test_window]

        def _filter(d: list) -> pd.DataFrame:
            if isinstance(df.index, pd.MultiIndex):
                return df.loc[df.index.get_level_values("date").isin(d)]
            return df.loc[df.index.isin(d)]

        folds.append({
            "train": _filter(train_dates),
            "val": _filter(val_dates),
            "test": _filter(test_dates),
        })

        i += step

    logger.info(f"Created {len(folds)} time-slice folds")
    return folds


def split_features_target(
    df: pd.DataFrame,
    feature_cols: list[str] | None = None,
    target_col: str = "target",
) -> Tuple[pd.DataFrame, pd.Series]:
    """Split DataFrame into feature matrix and target vector.

    Args:
        df: DataFrame with features and target.
        feature_cols: Optional explicit feature columns.
        target_col: Target column name.

    Returns:
        (X, y) tuple.
    """
    exclude = {"target", "open", "high", "low", "close", "adj_close", "volume"}
    if target_col:
        exclude.add(target_col)

    if feature_cols is None:
        feature_cols = [c for c in df.columns if c not in exclude]

    X = df[feature_cols].select_dtypes(include=[np.number])
    y = df[target_col]

    # Fill remaining NaN with 0
    X = X.fillna(0.0)
    y = y.fillna(0.0)

    return X, y
