"""services/factor_service/evaluation/ic_analysis.py – Information Coefficient analysis.

Computes:
- Rank IC (Spearman correlation between factor values and forward returns)
- IC Mean, IC Std, Information Ratio (IC Mean / IC Std)
- Rolling IC with configurable window
- IC cumulative curve
- Monthly IC heatmap data
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from services.factor_service.config import factor_config


class ICAnalyzer:
    """Analyzes factor Information Coefficient (predictive power).

    IC = cross-sectional rank correlation between factor values
    at time t and forward returns over horizon h.

    Attributes:
        rolling_window: Default rolling window for IC statistics.
    """

    def __init__(self, rolling_window: int | None = None) -> None:
        self.rolling_window = rolling_window or factor_config.IC_ROLLING_WINDOW

    def compute_ic(
        self,
        factor_values: pd.Series,
        forward_returns: pd.Series,
        method: str = "spearman",
    ) -> dict[str, Any]:
        """Compute IC statistics for a factor.

        Args:
            factor_values: Factor values indexed by date.
            forward_returns: Forward returns indexed by date (same index).
            method: Correlation method ('spearman' or 'pearson').

        Returns:
            Dictionary with IC statistics and time-series.
        """
        # Align indices
        common_idx = factor_values.index.intersection(forward_returns.index)
        if len(common_idx) < self.rolling_window:
            logger.warning(f"Insufficient data for IC: {len(common_idx)} < {self.rolling_window}")
            return {
                "rank_ic_mean": np.nan,
                "rank_ic_std": np.nan,
                "information_ratio": np.nan,
                "ic_series": [],
                "ic_cumulative": [],
            }

        fv = factor_values.loc[common_idx]
        fr = forward_returns.loc[common_idx]

        if method == "spearman":
            ic_series = fv.rolling(self.rolling_window).apply(
                lambda x: x.corr(fr.loc[x.index], method="spearman"), raw=False
            )
        else:
            ic_series = fv.rolling(self.rolling_window).corr(fr)

        ic_series = ic_series.dropna()

        if ic_series.empty:
            return {"rank_ic_mean": np.nan, "rank_ic_std": np.nan, "information_ratio": np.nan}

        ic_mean = float(ic_series.mean())
        ic_std = float(ic_series.std())
        ir = ic_mean / ic_std if ic_std > 0 else 0.0

        # IC cumulative
        ic_cumsum = ic_series.cumsum()

        # Monthly IC heatmap data
        monthly_ic = self._monthly_ic(fv, fr)

        return {
            "rank_ic_mean": round(ic_mean, 6),
            "rank_ic_std": round(ic_std, 6),
            "information_ratio": round(ir, 4),
            "ic_t_stat": round(ic_mean / (ic_std / np.sqrt(len(ic_series))) if ic_std > 0 else 0.0, 4),
            "positive_ic_ratio": round(float((ic_series > 0).mean()), 4),
            "rolling_window": self.rolling_window,
            "num_observations": len(ic_series),
            "ic_series": [
                {"date": str(d.date()), "ic": round(v, 6)}
                for d, v in ic_series.items()
            ],
            "ic_cumulative": [
                {"date": str(d.date()), "cumulative_ic": round(v, 6)}
                for d, v in ic_cumsum.items()
            ],
            "monthly_ic": monthly_ic,
        }

    def _monthly_ic(
        self,
        factor_values: pd.Series,
        forward_returns: pd.Series,
    ) -> list[dict[str, Any]]:
        """Compute monthly average IC for heatmap.

        Args:
            factor_values: Factor values.
            forward_returns: Forward returns.

        Returns:
            List of monthly IC dicts.
        """
        common = factor_values.index.intersection(forward_returns.index)
        if len(common) < 20:
            return []

        fv = factor_values.loc[common]
        fr = forward_returns.loc[common]

        result: list[dict[str, Any]] = []
        for (year, month), group in fv.groupby([fv.index.year, fv.index.month]):
            if len(group) < 5:
                continue
            gr = fr.loc[group.index]
            ic = group.corr(gr, method="spearman")
            result.append({
                "year": int(year),
                "month": int(month),
                "ic": round(float(ic), 6),
            })

        return result

    def compute_ic_summary_table(
        self,
        factors: dict[str, pd.Series],
        forward_returns: pd.Series,
    ) -> pd.DataFrame:
        """Compute IC summary for multiple factors.

        Args:
            factors: Dict of factor_name → Series.
            forward_returns: Forward returns Series.

        Returns:
            DataFrame with IC stats per factor.
        """
        rows = []
        for name, series in factors.items():
            result = self.compute_ic(series, forward_returns)
            rows.append({
                "factor": name,
                "ic_mean": result["rank_ic_mean"],
                "ic_std": result["rank_ic_std"],
                "ir": result["information_ratio"],
                "ic_t_stat": result.get("ic_t_stat", np.nan),
            })

        df = pd.DataFrame(rows)
        df = df.sort_values("ir", ascending=False)
        return df
