"""services/data_service/pipeline/cleanser.py – Data cleansing pipeline.

Operations:
1. Missing value detection & forward-fill (with max gap threshold)
2. Outlier detection via Z-score (configurable threshold)
3. Price adjustment for splits & dividends (adj_close alignment)
4. Duplicate removal
5. Data quality scoring
"""

from __future__ import annotations

from datetime import date
from typing import Optional, Tuple

import numpy as np
import pandas as pd
from loguru import logger

from services.data_service.config import data_config


class DataCleanser:
    """Cleans and validates market data before storage.

    Attributes:
        zscore_threshold: Z-score beyond which values are flagged as outliers.
        max_missing_pct: Maximum allowed missing value percentage.
        min_bar_count: Minimum required bars for a valid dataset.
    """

    def __init__(
        self,
        zscore_threshold: float | None = None,
        max_missing_pct: float | None = None,
        min_bar_count: int | None = None,
    ) -> None:
        self.zscore_threshold = zscore_threshold or data_config.ZSCORE_OUTLIER_THRESHOLD
        self.max_missing_pct = max_missing_pct or data_config.MAX_MISSING_PCT
        self.min_bar_count = min_bar_count or data_config.MIN_BAR_COUNT

    def clean(self, df: pd.DataFrame, ticker: str = "unknown") -> pd.DataFrame:
        """Run full cleansing pipeline on a DataFrame.

        Args:
            df: Raw OHLCV DataFrame indexed by date.
            ticker: Ticker symbol for logging.

        Returns:
            Cleaned DataFrame.

        Raises:
            ValueError: If data quality is too poor.
        """
        if df is None or df.empty:
            raise ValueError(f"No data to clean for {ticker}")

        original_len = len(df)

        # 1. Remove duplicates
        df = df[~df.index.duplicated(keep="first")]

        # 2. Ensure proper column names (lowercase)
        df.columns = [c.lower().replace(" ", "_") for c in df.columns]

        # 3. Fill missing values (forward-fill, then backward)
        df = df.ffill(limit=5)  # Max 5 consecutive FFill
        df = df.bfill(limit=2)  # Max 2 consecutive BFill

        # 4. Detect and handle outliers in OHLC
        for col in ["open", "high", "low", "close"]:
            if col in df.columns:
                df = self._handle_outliers(df, col)

        # 5. Ensure adj_close consistency
        if "adj_close" in df.columns and "close" in df.columns:
            # If adj_close is all NaN, use close
            if df["adj_close"].isna().all():
                df["adj_close"] = df["close"]
            # Fill gaps in adj_close with proportional mapping
            if df["adj_close"].isna().any():
                ratio = df["adj_close"] / df["close"]
                median_ratio = ratio.median()
                df.loc[df["adj_close"].isna(), "adj_close"] = (
                    df.loc[df["adj_close"].isna(), "close"] * median_ratio
                )

        # 6. Quality check
        self._quality_check(df, ticker, original_len)

        cleaned_len = len(df)
        if cleaned_len < original_len:
            logger.info(f"Cleanser: {ticker} {original_len}→{cleaned_len} bars")

        return df

    def _handle_outliers(self, df: pd.DataFrame, col: str) -> pd.DataFrame:
        """Detect and winsorize outliers using Z-score.

        Args:
            df: DataFrame.
            col: Column name to check.

        Returns:
            DataFrame with outliers capped.
        """
        values = df[col].dropna()
        if len(values) < 10:
            return df

        z_scores = np.abs((values - values.mean()) / values.std().clip(min=1e-8))
        outliers = z_scores > self.zscore_threshold
        outlier_pct = outliers.mean()

        if outlier_pct > 0.01:  # Only log if > 1% outliers
            logger.debug(f"Column {col}: {outlier_pct:.1%} outliers detected (threshold={self.zscore_threshold})")

        # Winsorize: cap at threshold * std from mean
        cap_upper = values.mean() + self.zscore_threshold * values.std()
        cap_lower = values.mean() - self.zscore_threshold * values.std()
        df[col] = df[col].clip(lower=cap_lower, upper=cap_upper)

        return df

    def _quality_check(self, df: pd.DataFrame, ticker: str, original_len: int) -> None:
        """Validate data quality meets minimum thresholds.

        Args:
            df: Cleaned DataFrame.
            ticker: Ticker for logging.
            original_len: Original row count.

        Raises:
            ValueError: If quality checks fail.
        """
        issues: list[str] = []

        # Bar count check
        if len(df) < self.min_bar_count:
            issues.append(f"Only {len(df)} bars (min: {self.min_bar_count})")

        # Missing value check
        required_cols = ["open", "high", "low", "close", "volume"]
        for col in required_cols:
            if col in df.columns:
                missing_pct = df[col].isna().mean()
                if missing_pct > self.max_missing_pct:
                    issues.append(f"{col}: {missing_pct:.1%} missing (max: {self.max_missing_pct:.1%})")

        # Basic sanity checks
        if "high" in df.columns and "low" in df.columns:
            invalid = (df["high"] < df["low"]).mean()
            if invalid > 0.01:
                issues.append(f"High < Low in {invalid:.1%} of bars")

        if "close" in df.columns and "open" in df.columns:
            zero_close = (df["close"] <= 0).mean()
            if zero_close > 0:
                issues.append(f"Non-positive close in {zero_close:.1%} of bars")

        if issues:
            summary = "; ".join(issues)
            logger.warning(f"Data quality issues for {ticker}: {summary}")

        if len(df) < self.min_bar_count:
            raise ValueError(f"Insufficient data for {ticker}: {len(df)} bars < {self.min_bar_count}")

    def compute_quality_score(self, df: pd.DataFrame) -> float:
        """Compute a data quality score from 0.0 (worst) to 1.0 (best).

        Args:
            df: DataFrame to score.

        Returns:
            Quality score.
        """
        scores: list[float] = []

        # Completeness score
        completeness = 1.0 - df.isna().mean().mean()
        scores.append(max(completeness, 0.0))

        # Consistency score (no high < low)
        if "high" in df.columns and "low" in df.columns:
            consistency = 1.0 - (df["high"] < df["low"]).mean()
            scores.append(max(consistency, 0.0))

        # Volume sanity (no negative volume)
        if "volume" in df.columns:
            vol_ok = 1.0 - (df["volume"] < 0).mean()
            scores.append(max(vol_ok, 0.0))

        return float(np.mean(scores)) if scores else 0.0
