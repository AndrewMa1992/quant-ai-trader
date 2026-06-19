"""services/factor_service/evaluation/correlation.py – Factor correlation analysis.

Computes:
- Spearman correlation matrix
- Pearson correlation matrix
- Redundant factor detection (> threshold)
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from services.factor_service.config import factor_config


class FactorCorrelation:
    """Analyzes cross-sectional correlations between factors.

    Detects redundant factor pairs and provides clustering suggestions.

    Attributes:
        threshold: Correlation threshold for redundant factor detection.
    """

    def __init__(self, threshold: float | None = None) -> None:
        self.threshold = threshold or factor_config.CORRELATION_THRESHOLD

    def compute_correlation_matrix(
        self,
        df: pd.DataFrame,
        method: str = "spearman",
    ) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
        """Compute pairwise factor correlation matrix.

        Args:
            df: DataFrame with factor columns.
            method: 'spearman' or 'pearson'.

        Returns:
            Tuple of (correlation DataFrame, list of redundant pairs).
        """
        # Only numeric columns
        factor_cols = df.select_dtypes(include=[np.number]).columns.tolist()

        if len(factor_cols) < 2:
            logger.warning("Need at least 2 factor columns for correlation")
            return pd.DataFrame(), []

        corr_df = df[factor_cols].corr(method=method)

        # Detect redundant pairs
        redundant_pairs = self._find_redundant(corr_df)

        return corr_df, redundant_pairs

    def _find_redundant(self, corr_df: pd.DataFrame) -> list[dict[str, Any]]:
        """Find factor pairs with correlation above threshold.

        Args:
            corr_df: Correlation matrix DataFrame.

        Returns:
            List of redundant pair dicts.
        """
        redundant: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        for i in range(len(corr_df.columns)):
            for j in range(i + 1, len(corr_df.columns)):
                val = corr_df.iloc[i, j]
                if abs(val) >= self.threshold:
                    f1 = str(corr_df.columns[i])
                    f2 = str(corr_df.columns[j])
                    pair = tuple(sorted([f1, f2]))
                    if pair not in seen:
                        seen.add(pair)
                        redundant.append({
                            "factor_1": f1,
                            "factor_2": f2,
                            "correlation": round(float(val), 4),
                            "abs_correlation": round(abs(float(val)), 4),
                        })

        # Sort by absolute correlation descending
        redundant.sort(key=lambda x: x["abs_correlation"], reverse=True)
        return redundant

    def compute_correlation_with_returns(
        self,
        factor_df: pd.DataFrame,
        returns: pd.Series,
        method: str = "spearman",
    ) -> pd.Series:
        """Compute correlation of each factor with forward returns.

        Args:
            factor_df: DataFrame of factor values.
            returns: Forward return series.
            method: Correlation method.

        Returns:
            Series of correlations indexed by factor name.
        """
        factor_cols = factor_df.select_dtypes(include=[np.number]).columns
        result: dict[str, float] = {}

        for col in factor_cols:
            common = factor_df[col].dropna().index.intersection(returns.dropna().index)
            if len(common) < 30:
                result[str(col)] = np.nan
                continue

            if method == "spearman":
                result[str(col)] = factor_df[col].loc[common].corr(
                    returns.loc[common], method="spearman"
                )
            else:
                result[str(col)] = factor_df[col].loc[common].corr(
                    returns.loc[common], method="pearson"
                )

        return pd.Series(result).sort_values(ascending=False)

    def find_clusters(
        self,
        corr_df: pd.DataFrame,
        min_cluster_size: int = 2,
    ) -> list[list[str]]:
        """Simple greedy clustering of correlated factors.

        Args:
            corr_df: Correlation matrix.
            min_cluster_size: Minimum number of factors to form a cluster.

        Returns:
            List of clusters (each cluster is a list of factor names).
        """
        n = len(corr_df.columns)
        visited: set[int] = set()
        clusters: list[list[str]] = []

        for i in range(n):
            if i in visited:
                continue
            cluster = [str(corr_df.columns[i])]
            visited.add(i)

            for j in range(n):
                if j in visited:
                    continue
                if abs(corr_df.iloc[i, j]) >= self.threshold:
                    cluster.append(str(corr_df.columns[j]))
                    visited.add(j)

            if len(cluster) >= min_cluster_size:
                clusters.append(cluster)

        return clusters
