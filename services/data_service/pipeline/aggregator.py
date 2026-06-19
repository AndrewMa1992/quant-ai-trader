"""services/data_service/pipeline/aggregator.py – Data aggregation utilities.

Converts:
- Daily bars → Weekly / Monthly
- Minute bars → Hourly / Daily
- Cross-market time alignment
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

import pandas as pd


class AggFrequency(str, Enum):
    """Aggregation frequency options."""
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    HOURLY = "hourly"
    DAILY = "daily"


class DataAggregator:
    """Aggregates OHLCV data to lower frequencies.

    Supports resampling of daily and minute bar data.
    """

    @staticmethod
    def daily_to_weekly(df: pd.DataFrame) -> pd.DataFrame:
        """Aggregate daily bars to weekly.

        Uses Friday as the week-ending day.

        Args:
            df: Daily OHLCV DataFrame.

        Returns:
            Weekly OHLCV DataFrame.
        """
        if df.empty:
            return df

        ohlc_map = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "adj_close": "last",
        }
        vol_map = {"volume": "sum"}

        # Resample to week ending Friday
        weekly_ohlc = df.resample("W-FRI").agg(
            {k: v for k, v in ohlc_map.items() if k in df.columns}
        )
        weekly_vol = df.resample("W-FRI").agg(
            {k: v for k, v in vol_map.items() if k in df.columns}
        )

        result = pd.concat([weekly_ohlc, weekly_vol], axis=1)
        return result.dropna(how="all")

    @staticmethod
    def daily_to_monthly(df: pd.DataFrame) -> pd.DataFrame:
        """Aggregate daily bars to monthly.

        Args:
            df: Daily OHLCV DataFrame.

        Returns:
            Monthly OHLCV DataFrame.
        """
        if df.empty:
            return df

        ohlc_map = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "adj_close": "last",
        }
        vol_map = {"volume": "sum"}

        monthly_ohlc = df.resample("ME").agg(
            {k: v for k, v in ohlc_map.items() if k in df.columns}
        )
        monthly_vol = df.resample("ME").agg(
            {k: v for k, v in vol_map.items() if k in df.columns}
        )

        result = pd.concat([monthly_ohlc, monthly_vol], axis=1)
        return result.dropna(how="all")

    @staticmethod
    def minute_to_hourly(df: pd.DataFrame) -> pd.DataFrame:
        """Aggregate minute bars to hourly.

        Args:
            df: Minute OHLCV DataFrame indexed by datetime.

        Returns:
            Hourly OHLCV DataFrame.
        """
        if df.empty:
            return df

        ohlc_map = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
        }
        vol_map = {"volume": "sum", "trade_count": "sum"}

        hourly_ohlc = df.resample("1h").agg(
            {k: v for k, v in ohlc_map.items() if k in df.columns}
        )
        hourly_vol = df.resample("1h").agg(
            {k: v for k, v in vol_map.items() if k in df.columns}
        )

        result = pd.concat([hourly_ohlc, hourly_vol], axis=1)
        return result.dropna(how="all")

    @staticmethod
    def minute_to_daily(df: pd.DataFrame) -> pd.DataFrame:
        """Aggregate minute bars to daily.

        Args:
            df: Minute OHLCV DataFrame.

        Returns:
            Daily OHLCV DataFrame.
        """
        if df.empty:
            return df

        ohlc_map = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
        }
        vol_map = {"volume": "sum", "trade_count": "sum"}

        daily_ohlc = df.resample("1D").agg(
            {k: v for k, v in ohlc_map.items() if k in df.columns}
        )
        daily_vol = df.resample("1D").agg(
            {k: v for k, v in vol_map.items() if k in df.columns}
        )

        result = pd.concat([daily_ohlc, daily_vol], axis=1)
        return result.dropna(how="all")

    @staticmethod
    def align_market_times(
        dfs: dict[str, pd.DataFrame],
        target_tz: str = "UTC",
    ) -> dict[str, pd.DataFrame]:
        """Align DataFrames from multiple markets to common timezone.

        Args:
            dfs: Dict of market → DataFrame.
            target_tz: Target timezone for alignment.

        Returns:
            Dict of market → aligned DataFrame.
        """
        aligned: dict[str, pd.DataFrame] = {}
        for market, df in dfs.items():
            if df.empty:
                aligned[market] = df
                continue

            aligned_df = df.copy()
            if isinstance(aligned_df.index, pd.DatetimeIndex):
                if aligned_df.index.tz is None:
                    aligned_df.index = aligned_df.index.tz_localize("UTC")
                aligned_df.index = aligned_df.index.tz_convert(target_tz)
            aligned[market] = aligned_df

        return aligned

    @staticmethod
    def compute_returns(df: pd.DataFrame, periods: list[int] | None = None) -> pd.DataFrame:
        """Compute returns at multiple periods from close prices.

        Args:
            df: DataFrame with 'close' column.
            periods: List of return periods (e.g. [1, 5, 21]).

        Returns:
            DataFrame with added return columns.
        """
        periods = periods or [1, 5, 21, 63, 252]
        result = df.copy()
        col = "adj_close" if "adj_close" in df.columns else "close"

        if col not in result.columns:
            return result

        for p in periods:
            result[f"ret_{p}d"] = result[col].pct_change(periods=p)

        return result
