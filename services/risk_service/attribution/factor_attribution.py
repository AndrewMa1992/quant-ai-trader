"""services/risk_service/attribution/factor_attribution.py – Factor-based return attribution.

Fama-French / Carhart multi-factor decomposition:
R_i - R_f = α + β_mkt * (R_m - R_f) + β_smb * SMB + β_hml * HML + β_wml * WML + ε
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from services.data_service.storage.parquet_store import ParquetStore


class FactorAttribution:
    """Factor-based performance attribution using Fama-French/Carhart.

    Decomposes returns into market, size, value, momentum, and alpha components.
    """

    FACTOR_NAMES: list[str] = ["market", "size", "value", "momentum", "alpha"]

    def __init__(self) -> None:
        self._store = ParquetStore()

    def attribute(
        self,
        tickers: list[str],
        weights: list[float],
    ) -> dict[str, Any]:
        """Run factor attribution on a portfolio.

        Args:
            tickers: Portfolio tickers.
            weights: Portfolio weights.

        Returns:
            Factor attribution breakdown.
        """
        # Portfolio returns
        portfolio_returns = self._get_portfolio_returns(tickers, weights)
        if portfolio_returns is None or len(portfolio_returns) < 60:
            return {"error": "Insufficient data"}

        # Factor returns (approximated)
        # Market: SPY return
        # SMB: small-cap - large-cap (IJR - SPY)
        # HML: value - growth (IVE - IVW)
        # WML: winners - losers (MTUM approximation)
        market_ret = self._get_ticker_returns("SPY")
        small_ret = self._get_ticker_returns("IJR")
        large_ret = self._get_ticker_returns("SPY")
        value_ret = self._get_ticker_returns("IVE")
        growth_ret = self._get_ticker_returns("IVW")

        factors: dict[str, np.ndarray] = {}

        if market_ret is not None:
            factors["market"] = market_ret.values
        else:
            factors["market"] = np.zeros(len(portfolio_returns))

        if small_ret is not None and large_ret is not None:
            min_len = min(len(small_ret), len(large_ret))
            factors["size"] = (small_ret.values[:min_len] - large_ret.values[:min_len])
        else:
            factors["size"] = np.zeros(len(portfolio_returns))

        if value_ret is not None and growth_ret is not None:
            min_len = min(len(value_ret), len(growth_ret))
            factors["value"] = (value_ret.values[:min_len] - growth_ret.values[:min_len])
        else:
            factors["value"] = np.zeros(len(portfolio_returns))

        # Momentum: 12-month winner - loser approximation
        factors["momentum"] = np.zeros(len(portfolio_returns))

        # Align all series
        min_len = min(
            len(portfolio_returns),
            *[len(f) for f in factors.values()],
        )

        port = portfolio_returns[-min_len:]
        X = np.column_stack([factors[k][-min_len:] for k in ["market", "size", "value", "momentum"]])

        # Regression
        try:
            betas = np.linalg.lstsq(X, port, rcond=None)[0]
            residuals = port - X @ betas

            # Component contributions
            contributions: dict[str, float] = {}
            for i, name in enumerate(["market", "size", "value", "momentum"]):
                contributions[name] = float(betas[i] * X[:, i].mean())

            # Alpha
            alpha = float(np.mean(residuals))
            contributions["alpha"] = alpha

            r_squared = 1.0 - float(np.sum(residuals**2)) / float(np.sum((port - port.mean())**2))

            return {
                "factor_contributions": contributions,
                "betas": {
                    "market": round(float(betas[0]), 4),
                    "size": round(float(betas[1]), 4),
                    "value": round(float(betas[2]), 4),
                    "momentum": round(float(betas[3]), 4),
                },
                "alpha_annualized": round(float(alpha * 252), 6),
                "r_squared": round(r_squared, 4),
                "n_obs": min_len,
            }

        except np.linalg.LinAlgError:
            return {"error": "Regression failed", "factor_contributions": {}}

    def _get_ticker_returns(self, ticker: str) -> pd.Series | None:
        """Get daily returns for a ticker."""
        df = self._store.read_daily(ticker)
        if df is None or len(df) < 30:
            return None
        col = "adj_close" if "adj_close" in df.columns else "close"
        return df[col].pct_change().dropna()

    def _get_portfolio_returns(
        self,
        tickers: list[str],
        weights: list[float],
    ) -> np.ndarray | None:
        """Build portfolio weighted returns."""
        rets = []
        for ticker in tickers:
            ser = self._get_ticker_returns(ticker)
            if ser is not None:
                rets.append(ser)

        if len(rets) != len(tickers):
            return None

        combined = pd.concat(rets, axis=1, keys=tickers).dropna()
        if combined.empty:
            return None

        return (combined * np.array(weights)).sum(axis=1).values
