"""services/risk_service/risk_measures/var.py – Value at Risk estimation.

Three methods:
1. Parametric (normal and Student-t)
2. Historical simulation (rolling window)
3. Monte Carlo (GBM simulation, 10000 paths)
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from services.data_service.storage.parquet_store import ParquetStore
from services.risk_service.config import risk_config


class VaRCalculator:
    """Value at Risk calculator with three estimation methods.

    Attributes:
        confidence: Confidence level (e.g. 0.95 for 95% VaR).
        rolling_window: Window for historical simulation.
        mc_paths: Number of Monte Carlo paths.
        mc_steps: Number of simulation steps.
    """

    def __init__(
        self,
        confidence: float | None = None,
        rolling_window: int | None = None,
        mc_paths: int | None = None,
    ) -> None:
        self.confidence = confidence or risk_config.VAR_CONFIDENCE
        self.rolling_window = rolling_window or risk_config.VAR_ROLLING_WINDOW
        self.mc_paths = mc_paths or risk_config.VAR_MONTE_CARLO_PATHS
        self._store = ParquetStore()

    def compute(
        self,
        tickers: list[str],
        weights: list[float],
        method: str = "parametric",
    ) -> dict[str, Any]:
        """Compute portfolio VaR.

        Args:
            tickers: Portfolio tickers.
            weights: Portfolio weights.
            method: 'parametric', 'historical', or 'montecarlo'.

        Returns:
            Dictionary with VaR estimate and diagnostics.
        """
        returns = self._get_portfolio_returns(tickers, weights)
        if returns is None or len(returns) < 30:
            return {"var": 0.0, "method": method, "error": "Insufficient data"}

        if method == "parametric":
            result = self._parametric_var(returns)
        elif method == "historical":
            result = self._historical_var(returns)
        elif method == "montecarlo":
            result = self._monte_carlo_var(returns)
        else:
            raise ValueError(f"Unknown VaR method: {method}")

        return result

    def _parametric_var(self, returns: np.ndarray) -> dict[str, Any]:
        """Parametric VaR using normal and Student-t distributions.

        Args:
            returns: Portfolio return array.

        Returns:
            VaR results.
        """
        mu = float(np.mean(returns))
        sigma = float(np.std(returns, ddof=1))

        # Normal VaR
        from scipy.stats import norm
        z_score_norm = norm.ppf(1.0 - self.confidence)
        var_normal = float(-(mu + z_score_norm * sigma))

        # Student-t VaR (with degrees of freedom estimation)
        try:
            from scipy.stats import t
            df_t = max(3, len(returns) - 2)
            z_score_t = t.ppf(1.0 - self.confidence, df_t)
            var_student = float(-(mu + z_score_t * sigma * np.sqrt(df_t / (df_t - 2))))
        except Exception:
            var_student = var_normal

        return {
            "var_normal": round(var_normal, 6),
            "var_student_t": round(var_student, 6),
            "method": "parametric",
            "confidence": self.confidence,
            "mu": round(mu, 6),
            "sigma": round(sigma, 6),
            "n_obs": len(returns),
        }

    def _historical_var(self, returns: np.ndarray) -> dict[str, Any]:
        """Historical simulation VaR.

        Args:
            returns: Portfolio returns.

        Returns:
            VaR results.
        """
        n = len(returns)
        window = min(self.rolling_window, n)
        recent = returns[-window:]

        var_val = float(-np.percentile(recent, (1.0 - self.confidence) * 100))

        return {
            "var": round(var_val, 6),
            "method": "historical",
            "confidence": self.confidence,
            "window": window,
            "n_obs": len(recent),
        }

    def _monte_carlo_var(self, returns: np.ndarray) -> dict[str, Any]:
        """Monte Carlo VaR via GBM simulation.

        Args:
            returns: Historical returns for parameter estimation.

        Returns:
            VaR results.
        """
        np.random.seed(42)

        mu = float(np.mean(returns))
        sigma = float(np.std(returns, ddof=1))

        # GBM: S_t = S_0 * exp((mu - 0.5*sigma^2)*t + sigma*sqrt(t)*Z)
        dt = 1.0 / 252
        drift = (mu - 0.5 * sigma**2) * dt
        diffusion = sigma * np.sqrt(dt)

        paths = np.random.randn(self.mc_paths, self.rolling_window)
        log_returns = drift + diffusion * paths
        cumulative = np.exp(log_returns.sum(axis=1)) - 1.0

        var_val = float(-np.percentile(cumulative, (1.0 - self.confidence) * 100))

        return {
            "var": round(var_val, 6),
            "method": "montecarlo",
            "confidence": self.confidence,
            "n_paths": self.mc_paths,
            "sim_days": self.rolling_window,
            "expected_return": round(float(cumulative.mean()), 6),
        }

    def _get_portfolio_returns(
        self,
        tickers: list[str],
        weights: list[float],
    ) -> np.ndarray | None:
        """Build weighted portfolio returns series.

        Args:
            tickers: Portfolio tickers.
            weights: Portfolio weights.

        Returns:
            Portfolio return array or None.
        """
        rets: list[pd.Series] = []
        for ticker in tickers:
            df = self._store.read_daily(ticker)
            if df is None or len(df) < 30:
                continue
            col = "adj_close" if "adj_close" in df.columns else "close"
            rets.append(df[col].pct_change().dropna())

        if len(rets) != len(tickers):
            return None

        combined = pd.concat(rets, axis=1, keys=tickers).dropna()
        if combined.empty:
            return None

        weighted = (combined * np.array(weights)).sum(axis=1)
        return weighted.values
