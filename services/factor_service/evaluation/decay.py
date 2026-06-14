"""services/factor_service/evaluation/decay.py – Factor IC decay analysis.

Measures how quickly a factor's predictive power decays over time.
Key metric: IC half-life (number of periods until IC drops to half its peak).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from services.factor_service.config import factor_config


class DecayAnalyzer:
    """Analyzes factor IC decay over multiple forward horizons.

    Computes IC at lags 1, 2, 3, ..., max_lags and estimates half-life.

    Attributes:
        max_lags: Maximum number of forward periods to test.
    """

    def __init__(self, max_lags: int | None = None) -> None:
        self.max_lags = max_lags or factor_config.DECAY_MAX_LAGS

    def analyze(
        self,
        factor_values: pd.Series,
        returns: pd.Series,
    ) -> dict[str, Any]:
        """Compute IC decay curve for a factor.

        Args:
            factor_values: Factor values indexed by date.
            returns: Daily return series (used to build multi-period forward returns).

        Returns:
            Dictionary with decay curve, half-life estimate, and statistics.
        """
        if len(factor_values) < 100:
            return {"error": "Insufficient data", "half_life": None, "decay_curve": []}

        # Build multi-period forward returns
        ic_by_lag: dict[int, float] = {}

        for lag in range(1, self.max_lags + 1):
            forward_ret = returns.rolling(lag).sum().shift(-lag)
            common = factor_values.dropna().index.intersection(forward_ret.dropna().index)

            if len(common) < 30:
                ic_by_lag[lag] = np.nan
                continue

            fv = factor_values.loc[common]
            fr = forward_ret.loc[common]
            ic_by_lag[lag] = float(fv.corr(fr, method="spearman"))

        # Build decay curve
        decay_curve = [
            {"lag": lag, "ic": round(ic, 6)}
            for lag, ic in ic_by_lag.items()
        ]

        # Estimate half-life
        half_life = self._estimate_half_life(ic_by_lag)

        # Peak IC
        valid_ics = {k: v for k, v in ic_by_lag.items() if not np.isnan(v)}
        peak_lag = max(valid_ics, key=valid_ics.get) if valid_ics else 1
        peak_ic = valid_ics.get(peak_lag, 0.0)

        return {
            "half_life": half_life,
            "peak_ic": round(peak_ic, 6),
            "peak_lag": peak_lag,
            "current_ic": round(ic_by_lag.get(1, np.nan), 6),
            "decay_curve": decay_curve,
            "decay_rate": round(self._compute_decay_rate(ic_by_lag), 6),
        }

    def _estimate_half_life(self, ic_by_lag: dict[int, float]) -> int | None:
        """Estimate IC half-life in trading days.

        Half-life is the first lag where IC drops below half of the peak IC.

        Args:
            ic_by_lag: Dict of lag → IC.

        Returns:
            Half-life in trading days, or None if indeterminable.
        """
        valid = {k: v for k, v in ic_by_lag.items() if not np.isnan(v)}
        if not valid:
            return None

        peak_abs = max(abs(v) for v in valid.values())
        if peak_abs < 0.001:
            return None

        half_threshold = peak_abs / 2.0

        for lag in sorted(valid.keys()):
            if abs(valid[lag]) < half_threshold:
                return lag

        return self.max_lags  # Hasn't decayed below half within max_lags

    def _compute_decay_rate(self, ic_by_lag: dict[int, float]) -> float:
        """Compute exponential decay rate via log-linear regression.

        Args:
            ic_by_lag: Dict of lag → IC.

        Returns:
            Decay rate λ where IC(t) ≈ IC(0) * exp(-λ * t).
        """
        valid = [(lag, abs(ic)) for lag, ic in ic_by_lag.items()
                 if not np.isnan(ic) and ic != 0 and lag > 0]

        if len(valid) < 3:
            return 0.0

        x = np.array([np.log(lag) for lag, _ in valid])
        y = np.array([np.log(ic) for _, ic in valid])

        # Simple linear regression: log(IC) = a + b * log(lag)
        slope = np.polyfit(x, y, 1)[0]
        return float(-slope)  # Positive decay rate


def compute_ic_across_horizons(
    factor_values: pd.Series,
    daily_returns: pd.Series,
    horizons: list[int] | None = None,
) -> pd.DataFrame:
    """Compute IC at multiple horizons for a factor.

    Args:
        factor_values: Factor values.
        daily_returns: Daily returns.
        horizons: List of horizons in trading days.

    Returns:
        DataFrame with columns: horizon, ic, t_stat.
    """
    horizons = horizons or [1, 5, 21, 63, 126, 252]
    results = []

    for h in horizons:
        fwd_ret = daily_returns.rolling(h).sum().shift(-h)
        common = factor_values.dropna().index.intersection(fwd_ret.dropna().index)

        if len(common) < 30:
            results.append({"horizon": h, "ic": np.nan, "t_stat": np.nan, "n": len(common)})
            continue

        fv = factor_values.loc[common]
        fr = fwd_ret.loc[common]
        ic = fv.corr(fr, method="spearman")
        t_stat = ic * np.sqrt(len(common) - 2) / np.sqrt(1 - ic**2) if abs(ic) < 1.0 else np.nan

        results.append({
            "horizon": h,
            "ic": round(float(ic), 6),
            "t_stat": round(float(t_stat), 4),
            "n": len(common),
        })

    return pd.DataFrame(results)
