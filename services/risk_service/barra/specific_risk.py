"""services/risk_service/barra/specific_risk.py – Specific / idiosyncratic risk estimation.

Residual volatility from market model regression.
Newey-West HAC standard errors for robust estimation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from loguru import logger

from services.data_service.storage.parquet_store import ParquetStore


class SpecificRiskEstimator:
    """Estimates specific (idiosyncratic) risk for each ticker.

    Specific risk = sqrt(total_variance - systematic_variance).

    Attributes:
        window: Rolling estimation window in trading days.
    """

    def __init__(self, window: int = 252) -> None:
        self.window = window
        self._store = ParquetStore()

    def estimate(self, ticker: str) -> dict[str, float]:
        """Estimate specific risk for a ticker.

        Args:
            ticker: Stock ticker symbol.

        Returns:
            Dict with specific_risk, systematic_risk, total_risk, r_squared.
        """
        df = self._store.read_daily(ticker)
        if df is None or len(df) < 63:
            return {"specific_risk": 0.0, "systematic_risk": 0.0, "total_risk": 0.0, "r_squared": 0.0}

        col = "adj_close" if "adj_close" in df.columns else "close"
        returns = df[col].pct_change().dropna().tail(self.window).values

        # Market proxy
        spy_df = self._store.read_daily("SPY")
        if spy_df is None or len(spy_df) < 63:
            total_risk = float(np.std(returns) * np.sqrt(252))
            return {"specific_risk": total_risk, "systematic_risk": 0.0, "total_risk": total_risk, "r_squared": 0.0}

        spy_col = "adj_close" if "adj_close" in spy_df.columns else "close"
        spy_returns = spy_df[spy_col].pct_change().dropna().values

        n = min(len(returns), len(spy_returns))
        returns = returns[-n:]
        spy_returns = spy_returns[-n:]

        # Market model regression
        X = np.column_stack([np.ones(n), spy_returns])
        beta_hat = np.linalg.lstsq(X, returns, rcond=None)[0]

        residuals = returns - X @ beta_hat

        # Total risk (annualized)
        total_risk = float(np.std(returns) * np.sqrt(252))

        # Systematic risk
        systematic_var = float(beta_hat[1]**2 * np.var(spy_returns))
        systematic_risk = float(np.sqrt(systematic_var) * np.sqrt(252))

        # Specific risk with HAC adjustment
        specific_risk = float(self._newey_west_se(residuals) * np.sqrt(252))

        # R-squared
        ss_res = float(np.sum(residuals**2))
        ss_tot = float(np.sum((returns - returns.mean())**2))
        r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

        return {
            "specific_risk": round(specific_risk, 6),
            "systematic_risk": round(systematic_risk, 6),
            "total_risk": round(total_risk, 6),
            "r_squared": round(r_squared, 4),
        }

    def _newey_west_se(self, residuals: np.ndarray, max_lag: int = 5) -> float:
        """Compute Newey-West HAC standard error.

        Args:
            residuals: Regression residuals.
            max_lag: Maximum autocorrelation lag.

        Returns:
            HAC standard error of the residuals.
        """
        n = len(residuals)
        if n < 2:
            return float(np.std(residuals)) if n > 0 else 0.0

        var = np.sum(residuals**2) / n
        for lag in range(1, min(max_lag + 1, n - 1)):
            weight = 1.0 - lag / (max_lag + 1)
            auto_cov = np.sum(residuals[lag:] * residuals[:-lag]) / n
            var += 2.0 * weight * auto_cov

        return float(np.sqrt(max(var, 0.0) / n)) * np.sqrt(n)

    def estimate_portfolio_specific_risk(
        self,
        tickers: list[str],
        weights: np.ndarray,
    ) -> float:
        """Estimate portfolio-level specific risk (diversifiable portion).

        Args:
            tickers: List of ticker symbols.
            weights: Portfolio weights (sum to 1).

        Returns:
            Annualized portfolio specific risk.
        """
        spec_var = 0.0
        for i, ticker in enumerate(tickers):
            result = self.estimate(ticker)
            spec_var += (weights[i] ** 2) * (result["specific_risk"] ** 2)

        return float(np.sqrt(max(spec_var, 0.0)))
