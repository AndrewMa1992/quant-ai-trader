"""services/data_service/pipeline/normalizer.py – Data normalization/standardization.

Three modes:
- Z-score: (x - mean) / std — zero mean, unit variance
- MinMax: (x - min) / (max - min) — [0, 1] range
- RobustScaler: (x - median) / IQR — outlier-resistant
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd


class NormMode(str, Enum):
    """Normalization mode enumeration."""
    ZSCORE = "zscore"
    MINMAX = "minmax"
    ROBUST = "robust"


class DataNormalizer:
    """Normalizes time-series data for factor computation and ML.

    Statistics computed on training window, applied to full series.
    """

    def __init__(self, mode: NormMode = NormMode.ZSCORE) -> None:
        self.mode = mode
        self._params: dict[str, dict[str, float]] = {}

    def fit(self, df: pd.DataFrame, columns: list[str] | None = None) -> "DataNormalizer":
        """Compute normalization parameters from a DataFrame.

        Args:
            df: Training data.
            columns: Columns to fit (defaults to all numeric).

        Returns:
            Self for chaining.
        """
        cols = columns or df.select_dtypes(include=[np.number]).columns.tolist()

        for col in cols:
            values = df[col].dropna()
            if len(values) < 2:
                continue

            if self.mode == NormMode.ZSCORE:
                self._params[col] = {
                    "mean": float(values.mean()),
                    "std": float(values.std().clip(min=1e-8)),
                }
            elif self.mode == NormMode.MINMAX:
                self._params[col] = {
                    "min": float(values.min()),
                    "max": float(values.max()),
                }
            elif self.mode == NormMode.ROBUST:
                self._params[col] = {
                    "median": float(values.median()),
                    "iqr": float(values.quantile(0.75) - values.quantile(0.25)).clip(lower=1e-8),
                }

        return self

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply fitted normalization to a DataFrame.

        Args:
            df: Data to normalize.

        Returns:
            Normalized DataFrame (copy).
        """
        result = df.copy()
        for col, params in self._params.items():
            if col not in result.columns:
                continue

            if self.mode == NormMode.ZSCORE:
                result[col] = (result[col] - params["mean"]) / params["std"]
            elif self.mode == NormMode.MINMAX:
                denom = params["max"] - params["min"]
                if denom > 1e-8:
                    result[col] = (result[col] - params["min"]) / denom
                else:
                    result[col] = 0.0
            elif self.mode == NormMode.ROBUST:
                result[col] = (result[col] - params["median"]) / params["iqr"]

        return result

    def fit_transform(
        self,
        df: pd.DataFrame,
        columns: list[str] | None = None,
    ) -> pd.DataFrame:
        """Fit and transform in one call.

        Args:
            df: Data to fit and normalize.
            columns: Columns to normalize.

        Returns:
            Normalized DataFrame.
        """
        self.fit(df, columns)
        return self.transform(df)

    def inverse_transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Reverse normalization back to original scale.

        Args:
            df: Normalized data.

        Returns:
            Original-scale DataFrame.
        """
        result = df.copy()
        for col, params in self._params.items():
            if col not in result.columns:
                continue

            if self.mode == NormMode.ZSCORE:
                result[col] = result[col] * params["std"] + params["mean"]
            elif self.mode == NormMode.MINMAX:
                denom = params["max"] - params["min"]
                result[col] = result[col] * denom + params["min"]
            elif self.mode == NormMode.ROBUST:
                result[col] = result[col] * params["iqr"] + params["median"]

        return result
