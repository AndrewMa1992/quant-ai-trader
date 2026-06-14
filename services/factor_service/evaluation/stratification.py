"""services/factor_service/evaluation/stratification.py – Stratified factor backtest.

Divides universe into quantile groups based on factor values
and computes forward returns for each group.

Outputs:
- Group returns (equal-weighted & cap-weighted)
- Long-short spread return
- Cumulative performance per group
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from services.factor_service.config import factor_config


class StratificationAnalyzer:
    """Performs stratified (quantile) backtest of a factor.

    Universe sorted by factor value, divided into n_quantiles groups.
    Forward returns tracked for each group.

    Attributes:
        n_quantiles: Number of groups (5 or 10).
        horizon: Forward return horizon ('1d', '5d', '21d').
    """

    def __init__(
        self,
        n_quantiles: int | None = None,
        horizon: str | None = None,
    ) -> None:
        self.n_quantiles = n_quantiles or factor_config.N_QUANTILES
        self.horizon = horizon or factor_config.STRATIFICATION_HORIZON
        self._horizon_days = self._parse_horizon(self.horizon)

    @staticmethod
    def _parse_horizon(horizon: str) -> int:
        """Parse horizon string to days.

        Args:
            horizon: e.g. '1d', '5d', '21d'.

        Returns:
            Number of trading days.
        """
        return int(horizon.replace("d", ""))

    def analyze(
        self,
        factor_values: pd.Series,
        forward_returns: pd.Series,
        weights: pd.Series | None = None,
    ) -> dict[str, Any]:
        """Stratify factor values and compute group performance.

        Args:
            factor_values: Factor values per date/ticker.
            forward_returns: Forward returns over the horizon.
            weights: Optional market-cap or equal weights.

        Returns:
            Dictionary with group returns and spread statistics.
        """
        # Align data
        common = factor_values.dropna().index.intersection(forward_returns.dropna().index)
        if len(common) < 50:
            return {"error": f"Insufficient data: {len(common)} obs", "groups": []}

        fv = factor_values.loc[common].dropna()
        fr = forward_returns.loc[fv.index]

        # Assign quantile groups
        group_labels = range(1, self.n_quantiles + 1)
        groups = pd.qcut(fv, self.n_quantiles, labels=group_labels, duplicates="drop")

        if groups.nunique() < 2:
            return {"error": "Unable to form distinct quantile groups", "groups": []}

        # Compute returns per group
        group_returns: dict[int, float] = {}
        group_counts: dict[int, int] = {}
        group_cum_returns: dict[int, list[float]] = {}

        for g in group_labels:
            mask = groups == g
            if mask.sum() == 0:
                continue

            if weights is not None:
                w = weights.loc[fv[mask].index]
                w = w / w.sum()
                avg_ret = (fr[mask] * w).sum()
            else:
                avg_ret = fr[mask].mean()

            group_returns[int(g)] = round(float(avg_ret), 6)
            group_counts[int(g)] = int(mask.sum())
            group_cum_returns[int(g)] = [round(float(avg_ret), 6)]

        # Long-short spread
        top_group = max(group_returns, key=group_returns.get)
        bottom_group = min(group_returns, key=group_returns.get)
        spread = group_returns[top_group] - group_returns[bottom_group]

        # Build group data for response
        group_data = []
        for g in sorted(group_returns.keys()):
            group_data.append({
                "quantile": g,
                "return": group_returns[g],
                "count": group_counts.get(g, 0),
            })

        return {
            "n_quantiles": self.n_quantiles,
            "horizon": self.horizon,
            "spread": round(spread, 6),
            "top_quantile": top_group,
            "bottom_quantile": bottom_group,
            "num_stocks": len(fv),
            "groups": group_data,
        }

    def rolling_stratification(
        self,
        factor_df: pd.DataFrame,
        returns: pd.Series,
        window: int = 252,
    ) -> pd.DataFrame:
        """Compute rolling stratification returns.

        Args:
            factor_df: Factor values (date × ticker).
            returns: Forward returns.
            window: Rolling window size.

        Returns:
            DataFrame with rolling long-short spread.
        """
        spreads: list[dict[str, Any]] = []
        dates = sorted(factor_df.index)

        for i in range(window, len(dates)):
            end_date = dates[i]
            start_date = dates[i - window]

            period_fv = factor_df.loc[start_date:end_date]
            if period_fv.empty:
                continue

            # Flatten to series
            flat_fv = period_fv.stack()
            flat_fr = returns.reindex(flat_fv.index)

            result = self.analyze(flat_fv, flat_fr)
            if "error" not in result:
                spreads.append({
                    "date": str(end_date.date()),
                    "spread": result["spread"],
                })

        return pd.DataFrame(spreads)
