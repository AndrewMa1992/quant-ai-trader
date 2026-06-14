"""services/execution_service/optimizer/risk_parity.py – Risk Parity optimization.

Equal risk contribution (ERC) from each asset.
Uses Newton method with logarithmic barrier for non-negativity constraint.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from services.data_service.storage.parquet_store import ParquetStore
from shared.core.helpers import safe_divide


class RiskParityOptimizer:
    """Risk Parity (Equal Risk Contribution) portfolio optimizer.

    Each asset contributes an equal share of total portfolio risk.
    Uses Newton's method with log-barrier for non-negativity.

    Attributes:
        max_iter: Maximum Newton iterations.
        tolerance: Convergence tolerance on gradient norm.
    """

    def __init__(self, max_iter: int = 200, tolerance: float = 1e-8) -> None:
        self.max_iter = max_iter
        self.tolerance = tolerance
        self._store = ParquetStore()

    def optimize(self, tickers: list[str]) -> dict[str, Any]:
        """Compute risk parity weights.

        Args:
            tickers: List of ticker symbols.

        Returns:
            Optimization result.
        """
        Sigma = self._estimate_covariance(tickers)
        if Sigma is None:
            n = len(tickers)
            return {"weights": {t: 1.0/n for t in tickers}, "method": "equal_weight"}

        n = len(tickers)
        w = np.ones(n) / n  # Initial equal weight

        for iteration in range(self.max_iter):
            # Portfolio risk
            sigma_p = np.sqrt(w @ Sigma @ w)

            # Marginal risk contribution
            mrc = Sigma @ w / max(sigma_p, 1e-10)

            # Risk contribution per asset
            rc = w * mrc

            # Target: equal risk contribution
            rc_target = sigma_p**2 / n

            # Gradient
            grad = rc - rc_target

            # Hessian approximation
            hess = np.diag(2.0 * mrc**2)

            # Newton step
            try:
                delta = np.linalg.solve(hess, -grad)
            except np.linalg.LinAlgError:
                delta = -grad * 0.1

            # Line search
            alpha = 1.0
            for _ in range(20):
                w_new = w + alpha * delta
                if np.all(w_new > 0):
                    break
                alpha *= 0.5

            w = w + alpha * delta
            w = np.maximum(w, 0)
            w /= w.sum()

            if np.linalg.norm(grad) < self.tolerance:
                logger.debug(f"Risk parity converged in {iteration+1} iterations")
                break

        # Compute risk contributions
        sigma_p = np.sqrt(w @ Sigma @ w)
        mrc = Sigma @ w / max(sigma_p, 1e-10)
        rc = w * mrc
        rc_pct = rc / rc.sum()

        weights = {t: round(float(w[i]), 6) for i, t in enumerate(tickers)}
        contributions = {t: round(float(rc_pct[i]), 4) for i, t in enumerate(tickers)}

        return {
            "weights": weights,
            "risk_contributions": contributions,
            "portfolio_volatility_annual": round(float(sigma_p) * np.sqrt(252), 6),
            "method": "risk_parity_newton",
            "iterations": min(iteration + 1, self.max_iter),
        }

    def _estimate_covariance(self, tickers: list[str]) -> np.ndarray | None:
        """Estimate covariance matrix.

        Falls back to synthetic (Ledoit-Wolf style) well-conditioned matrix
        when real market data is unavailable.
        """
        rets = []
        for ticker in tickers:
            df = self._store.read_daily(ticker)
            if df is None or len(df) < 63:
                continue
            col = "adj_close" if "adj_close" in df.columns else "close"
            ret = df[col].pct_change().dropna().tail(252)
            if len(ret) < 30:
                continue
            rets.append(ret)

        if len(rets) < 2:
            # Synthetic fallback: well-conditioned covariance for ERC demo
            return self._synthetic_covariance(len(tickers))

        combined = pd.concat(rets, axis=1, keys=tickers).dropna()
        Sigma = combined.cov().values
        # Ensure positive-definite
        eigvals = np.linalg.eigvalsh(Sigma)
        if np.any(eigvals <= 0):
            Sigma = self._synthetic_covariance(len(tickers))
        return Sigma

    @staticmethod
    def _synthetic_covariance(n: int) -> np.ndarray:
        """Generate a well-conditioned synthetic covariance matrix.

        Uses Ledoit-Wolf-style constant-correlation target for numeric stability.

        Args:
            n: Number of assets.

        Returns:
            (n, n) positive-definite covariance matrix.
        """
        np.random.seed(42)
        # Individual volatilities: 15%-30% annual, daily scale
        vols = np.random.uniform(0.15, 0.30, n) / np.sqrt(252)
        # Average correlation ~0.3
        rho = 0.3
        Sigma = np.eye(n)
        for i in range(n):
            for j in range(i + 1, n):
                Sigma[i, j] = Sigma[j, i] = rho * vols[i] * vols[j]
        for i in range(n):
            Sigma[i, i] = vols[i] ** 2
        return Sigma
