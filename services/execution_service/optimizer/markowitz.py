"""services/execution_service/optimizer/markowitz.py – Mean-Variance portfolio optimization.

Objective functions: max_sharpe / min_risk / max_return.
Uses cvxpy + OSQP for convex optimization.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from services.data_service.storage.parquet_store import ParquetStore
from services.execution_service.optimizer.constraints import ConstraintSystem
from shared.core.helpers import safe_divide


class MarkowitzOptimizer:
    """Mean-Variance portfolio optimizer.

    Supports 3 objectives:
    - max_sharpe: Maximize Sharpe ratio
    - min_risk: Minimize portfolio variance
    - max_return: Maximize expected return subject to risk constraint

    Attributes:
        objective: Optimization objective name.
        risk_free_rate: Annual risk-free rate.
    """

    def __init__(
        self,
        objective: str = "max_sharpe",
        risk_free_rate: float = 0.02,
    ) -> None:
        self.objective = objective
        self.risk_free_rate = risk_free_rate
        self._store = ParquetStore()
        self._constraints = ConstraintSystem()

    def optimize(
        self,
        tickers: list[str],
        constraints: dict | None = None,
    ) -> dict[str, Any]:
        """Run MV optimization.

        Args:
            tickers: List of ticker symbols.
            constraints: Optional constraint overrides.

        Returns:
            Optimization result with weights and diagnostics.
        """
        if len(tickers) < 2:
            return {"error": "Need at least 2 tickers", "weights": {}}

        # Build return and covariance estimates
        mu, Sigma = self._estimate_moments(tickers)

        if mu is None or Sigma is None:
            n = len(tickers)
            return {"weights": {t: 1.0/n for t in tickers}, "method": "equal_weight"}

        try:
            import cvxpy as cp

            n = len(tickers)
            w = cp.Variable(n)
            gamma = cp.Parameter(nonneg=True)

            # Expected return and risk
            portfolio_return = mu @ w
            portfolio_risk = cp.quad_form(w, Sigma)

            # Constraints
            constraints_list = [cp.sum(w) == 1.0] + self._constraints.build_cvxpy(w, n, constraints)

            if self.objective == "max_sharpe":
                # Approximate max Sharpe via max return/risk with risk-free
                rf_daily = self.risk_free_rate / 252
                objective_fn = cp.Maximize(portfolio_return - rf_daily * cp.sum(w))
                # Add risk constraint
                constraints_list.append(portfolio_risk <= 0.01)
            elif self.objective == "min_risk":
                objective_fn = cp.Minimize(portfolio_risk)
            elif self.objective == "max_return":
                objective_fn = cp.Maximize(portfolio_return)
                constraints_list.append(portfolio_risk <= 0.01)
            else:
                objective_fn = cp.Maximize(portfolio_return - cp.sqrt(portfolio_risk))

            problem = cp.Problem(objective_fn, constraints_list)
            problem.solve(solver=cp.OSQP, verbose=False)

            if w.value is None:
                weights = np.ones(n) / n
            else:
                weights = w.value
                weights = np.maximum(weights, 0)
                weights /= weights.sum()

            final_weights = {t: round(float(weights[i]), 6) for i, t in enumerate(tickers)}

            port_ret = float(mu @ weights)
            port_risk = float(np.sqrt(weights @ Sigma @ weights))
            sharpe = safe_divide(port_ret - self.risk_free_rate / 252, port_risk, 0.0) * np.sqrt(252)

            return {
                "weights": final_weights,
                "expected_return_annual": round(port_ret * 252, 6),
                "expected_volatility_annual": round(port_risk * np.sqrt(252), 6),
                "sharpe_ratio": round(sharpe, 4),
                "objective": self.objective,
                "method": "cvxpy_osqp",
            }

        except ImportError:
            return self._fallback_equal_weight(tickers)

    def _estimate_moments(self, tickers: list[str]) -> tuple[np.ndarray | None, np.ndarray | None]:
        """Estimate expected returns and covariance.

        Returns:
            (mu, Sigma) tuple or (None, None).
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
            return None, None

        combined = pd.concat(rets, axis=1, keys=tickers).dropna()
        mu = combined.mean().values
        Sigma = combined.cov().values

        return mu, Sigma

    def _fallback_equal_weight(self, tickers: list[str]) -> dict[str, Any]:
        n = len(tickers)
        return {
            "weights": {t: round(1.0/n, 6) for t in tickers},
            "method": "equal_weight_fallback",
            "objective": self.objective,
        }
