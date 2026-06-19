"""services/factor_service/evaluation/fama_macbeth.py – Fama-MacBeth regression.

Two-step procedure:
1. Cross-sectional regression at each time t:
   R_i = α + Σ β_k * Factor_{k,i} + ε_i
2. Time-series test of coefficient estimates:
   H₀: mean(β_k) = 0;  t-stat = mean(β_k) / (std(β_k) / √T)

Used to assess factor risk premia.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from loguru import logger


class FamaMacBeth:
    """Fama-MacBeth two-step regression for factor risk premia estimation.

    Step 1: For each time period, run cross-sectional regression
            of returns on factor exposures.
    Step 2: Compute time-series means and t-statistics of the
            estimated coefficients.

    Attributes:
        min_obs_per_period: Minimum cross-sectional observations per period.
        min_periods: Minimum time periods required.
    """

    def __init__(
        self,
        min_obs_per_period: int = 30,
        min_periods: int = 60,
    ) -> None:
        self.min_obs_per_period = min_obs_per_period
        self.min_periods = min_periods

    def run(
        self,
        returns: pd.DataFrame,
        factors: pd.DataFrame,
    ) -> dict[str, Any]:
        """Run Fama-MacBeth regression.

        Args:
            returns: DataFrame of asset returns (time × assets).
            factors: DataFrame of factor values (time × assets) with same columns
                     as returns.

        Returns:
            Dictionary with coefficient estimates and diagnostics.
        """
        if isinstance(returns, pd.Series) and isinstance(factors, pd.Series):
            # Single-factor case: reshape
            returns = returns.to_frame("return")
            factors = factors.to_frame(factors.name or "factor")

        common_dates = returns.index.intersection(factors.index)
        common_assets = returns.columns.intersection(factors.columns)

        if len(common_dates) < self.min_periods:
            return {
                "error": f"Insufficient time periods: {len(common_dates)} < {self.min_periods}",
                "coefficients": {},
            }

        if len(common_assets) < self.min_obs_per_period:
            return {
                "error": f"Insufficient cross-section: {len(common_assets)} < {self.min_obs_per_period}",
                "coefficients": {},
            }

        returns = returns.loc[common_dates, common_assets]
        factors = factors.loc[common_dates, common_assets]

        # Step 1: Cross-sectional regression per period
        coef_series: dict[str, list[float]] = {}

        for t in common_dates:
            y = returns.loc[t].dropna()
            X = factors.loc[t]

            # Align cross-section
            valid = y.index.intersection(X.dropna().index)
            if len(valid) < self.min_obs_per_period:
                continue

            y_valid = y.loc[valid].values
            X_valid = X.loc[valid].values.reshape(-1, 1) if isinstance(X, pd.Series) else X.loc[valid].values

            # Add constant
            if X_valid.ndim == 1:
                X_valid = X_valid.reshape(-1, 1)
            X_with_const = np.column_stack([np.ones(len(X_valid)), X_valid])

            try:
                beta = np.linalg.lstsq(X_with_const, y_valid, rcond=None)[0]
                # Store intercept
                if "alpha" not in coef_series:
                    coef_series["alpha"] = []
                coef_series["alpha"].append(float(beta[0]))

                # Store factor coefficients
                factor_names = ["factor"] if X_valid.shape[1] == 1 else list(factors.columns)
                for j, name in enumerate(factor_names):
                    if name not in coef_series:
                        coef_series[name] = []
                    coef_series[name].append(float(beta[j + 1]))
            except np.linalg.LinAlgError:
                continue

        # Step 2: Time-series statistics
        coefficients: dict[str, dict[str, float]] = {}
        for name, betas in coef_series.items():
            if len(betas) < self.min_periods:
                continue

            arr = np.array(betas)
            mean_beta = float(arr.mean())
            std_beta = float(arr.std(ddof=1))
            t_stat = mean_beta / (std_beta / np.sqrt(len(arr))) if std_beta > 0 else 0.0

            # Newey-West adjustment (lag=4)
            nw_se = self._newey_west_se(arr, max_lag=4)
            nw_t_stat = mean_beta / nw_se if nw_se > 0 else 0.0

            coefficients[name] = {
                "mean": round(mean_beta, 6),
                "std": round(std_beta, 6),
                "t_stat": round(t_stat, 4),
                "nw_t_stat": round(nw_t_stat, 4),
                "n_periods": len(arr),
            }

        return {
            "coefficients": coefficients,
            "n_time_periods": len(common_dates),
            "n_assets": len(common_assets),
            "total_regressions": max(len(v) for v in coef_series.values()) if coef_series else 0,
        }

    @staticmethod
    def _newey_west_se(series: np.ndarray, max_lag: int = 4) -> float:
        """Compute Newey-West HAC standard error.

        Args:
            series: Array of coefficient estimates.
            max_lag: Maximum autocorrelation lag.

        Returns:
            HAC standard error.
        """
        n = len(series)
        if n < 2:
            return float(np.std(series, ddof=1) / np.sqrt(n)) if n > 0 else np.inf

        # Variance (lag 0)
        residuals = series - series.mean()
        var = np.sum(residuals**2) / n

        # Autocovariance terms
        for lag in range(1, min(max_lag + 1, n - 1)):
            weight = 1.0 - lag / (max_lag + 1)
            auto_cov = np.sum(residuals[lag:] * residuals[:-lag]) / n
            var += 2.0 * weight * auto_cov

        return float(np.sqrt(var / n))

    def run_multi_factor(
        self,
        returns: pd.DataFrame,
        factor_dict: dict[str, pd.DataFrame],
    ) -> pd.DataFrame:
        """Run Fama-MacBeth with multiple factors.

        Args:
            returns: Asset returns (time × assets).
            factor_dict: Dict of factor_name → factor_values (time × assets).

        Returns:
            DataFrame of coefficient estimates for all factors.
        """
        all_factors = []
        for name, fdf in factor_dict.items():
            stacked = fdf.stack().rename(name)
            all_factors.append(stacked)

        combined = pd.concat(all_factors, axis=1)
        result = self.run(returns, combined)
        return pd.DataFrame(result.get("coefficients", {})).T
