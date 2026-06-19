"""services/risk_service/risk_measures/cvar.py – Conditional VaR / Expected Shortfall.

CVaR = mean of losses beyond VaR threshold.
Confidence levels: 95% and 99%.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from services.data_service.storage.parquet_store import ParquetStore
from services.risk_service.config import risk_config


class CVaRCalculator:
    """Conditional Value at Risk (Expected Shortfall) calculator.

    CVaR(α) = E[L | L > VaR(α)] where L = -return.

    Attributes:
        confidence: Confidence level (0.95 or 0.99).
    """

    def __init__(self, confidence: float | None = None) -> None:
        self.confidence = confidence or risk_config.VAR_CONFIDENCE
        self._store = ParquetStore()

    def compute(
        self,
        tickers: list[str],
        weights: list[float],
    ) -> dict[str, Any]:
        """Compute portfolio CVaR.

        Args:
            tickers: Portfolio tickers.
            weights: Portfolio weights.

        Returns:
            CVaR results.
        """
        returns = self._get_portfolio_returns(tickers, weights)
        if returns is None or len(returns) < 30:
            return {"cvar": 0.0, "error": "Insufficient data"}

        losses = -returns  # Loss > 0 means a loss

        # Compute VaR first
        var_threshold = float(np.percentile(losses, self.confidence * 100))

        # CVaR = mean of losses beyond VaR
        tail_losses = losses[losses >= var_threshold]
        cvar_val = float(tail_losses.mean()) if len(tail_losses) > 0 else var_threshold

        # Also compute at 99%
        var_99 = float(np.percentile(losses, 99))
        tail_99 = losses[losses >= var_99]
        cvar_99 = float(tail_99.mean()) if len(tail_99) > 0 else var_99

        return {
            "cvar_95": round(cvar_val, 6),
            "cvar_99": round(cvar_99, 6),
            "var_95": round(var_threshold, 6),
            "var_99": round(var_99, 6),
            "confidence": self.confidence,
            "tail_count_95": len(tail_losses),
            "tail_count_99": len(tail_99),
            "n_obs": len(returns),
            "tail_ratio_95": round(len(tail_losses) / max(len(returns), 1), 4),
        }

    def _get_portfolio_returns(
        self,
        tickers: list[str],
        weights: list[float],
    ) -> np.ndarray | None:
        """Build weighted portfolio returns."""
        rets: list[pd.Series] = []
        for ticker in tickers:
            df = self._store.read_daily(ticker)
            if df is None:
                continue
            col = "adj_close" if "adj_close" in df.columns else "close"
            rets.append(df[col].pct_change().dropna())

        if len(rets) != len(tickers):
            return None

        combined = pd.concat(rets, axis=1, keys=tickers).dropna()
        if combined.empty:
            return None

        return (combined * np.array(weights)).sum(axis=1).values

    def compute_distribution(self, losses: np.ndarray) -> dict[str, Any]:
        """Compute CVaR directly from a loss array.

        Args:
            losses: Array of portfolio losses (positive = loss).

        Returns:
            CVaR diagnostic dict.
        """
        var_95 = float(np.percentile(losses, 95))
        var_99 = float(np.percentile(losses, 99))

        tail_95 = losses[losses >= var_95]
        tail_99 = losses[losses >= var_99]

        return {
            "cvar_95": round(float(tail_95.mean()) if len(tail_95) > 0 else var_95, 6),
            "cvar_99": round(float(tail_99.mean()) if len(tail_99) > 0 else var_99, 6),
            "var_95": round(var_95, 6),
            "var_99": round(var_99, 6),
            "mean_loss": round(float(losses.mean()), 6),
            "max_loss": round(float(losses.max()), 6),
            "skewness": round(float(pd.Series(losses).skew()), 4),
            "kurtosis": round(float(pd.Series(losses).kurtosis()), 4),
        }
