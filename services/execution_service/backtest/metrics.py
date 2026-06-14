"""services/execution_service/backtest/metrics.py – Performance metrics.

Sharpe, Sortino, MaxDD, Calmar, annualized return, volatility,
win rate, profit factor, hit rate, IC.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from loguru import logger


class PerformanceMetrics:
    """Computes performance metrics from equity curve or trade log.

    All returns annualized assuming 252 trading days.
    """

    TRADING_DAYS: int = 252

    @staticmethod
    def from_equity_curve(
        equity: np.ndarray | list[float],
        risk_free_rate: float = 0.02,
    ) -> dict[str, Any]:
        """Compute all metrics from an equity curve.

        Args:
            equity: Array of portfolio values over time.
            risk_free_rate: Annual risk-free rate.

        Returns:
            Performance metrics dictionary.
        """
        equity = np.asarray(equity, dtype=float)
        if len(equity) < 2:
            return {"error": "Need at least 2 data points"}

        # Returns
        returns = np.diff(equity) / equity[:-1]
        n = len(returns)

        # Annualized return
        total_return = (equity[-1] / equity[0]) - 1.0
        years = n / PerformanceMetrics.TRADING_DAYS
        annual_return = (1.0 + total_return) ** (1.0 / max(years, 0.01)) - 1.0

        # Volatility
        annual_vol = float(np.std(returns, ddof=1) * np.sqrt(PerformanceMetrics.TRADING_DAYS))

        # Sharpe ratio
        excess = annual_return - risk_free_rate
        sharpe = excess / annual_vol if annual_vol > 0 else 0.0

        # Sortino ratio (downside deviation)
        downside_returns = returns[returns < 0]
        downside_std = float(np.std(downside_returns, ddof=1)) if len(downside_returns) > 0 else 0.0
        sortino = excess / (downside_std * np.sqrt(PerformanceMetrics.TRADING_DAYS)) if downside_std > 0 else 0.0

        # Max drawdown
        peak = np.maximum.accumulate(equity)
        drawdown = (equity - peak) / np.maximum(peak, 1e-10)
        max_dd = float(drawdown.min())

        # Calmar ratio
        calmar = annual_return / abs(max_dd) if max_dd < 0 else 0.0

        # Win rate
        winning_trades = int(np.sum(returns > 0))
        win_rate = winning_trades / n if n > 0 else 0.0

        # Profit factor
        gross_profit = float(np.sum(returns[returns > 0]))
        gross_loss = float(abs(np.sum(returns[returns < 0])))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Average trade
        avg_win = float(np.mean(returns[returns > 0])) if winning_trades > 0 else 0.0
        avg_loss = float(np.mean(returns[returns < 0])) if (n - winning_trades) > 0 else 0.0

        return {
            "total_return": round(total_return, 6),
            "total_return_pct": round(total_return * 100, 2),
            "annual_return": round(annual_return, 6),
            "annual_return_pct": round(annual_return * 100, 2),
            "annual_volatility": round(annual_vol, 6),
            "sharpe_ratio": round(sharpe, 4),
            "sortino_ratio": round(sortino, 4),
            "max_drawdown": round(max_dd, 6),
            "max_drawdown_pct": round(max_dd * 100, 2),
            "calmar_ratio": round(calmar, 4),
            "win_rate": round(win_rate, 4),
            "profit_factor": round(profit_factor, 4),
            "avg_win": round(avg_win, 6),
            "avg_loss": round(avg_loss, 6),
            "num_observations": n,
            "years": round(years, 2),
        }

    @staticmethod
    def from_trades(
        trades: list[dict[str, Any]],
        initial_capital: float = 1_000_000.0,
    ) -> dict[str, Any]:
        """Compute metrics from a list of trade records.

        Args:
            trades: List of {entry_price, exit_price, quantity, side, pnl}.
            initial_capital: Starting capital.

        Returns:
            Performance metrics.
        """
        if not trades:
            return {"error": "No trades"}

        pnls = [t.get("pnl", 0.0) for t in trades]
        total_pnl = sum(pnls)
        total_return = total_pnl / initial_capital

        winning = [p for p in pnls if p > 0]
        losing = [p for p in pnls if p < 0]

        win_rate = len(winning) / len(pnls) if pnls else 0.0
        avg_win = float(np.mean(winning)) if winning else 0.0
        avg_loss = float(np.mean(losing)) if losing else 0.0
        profit_factor = sum(winning) / abs(sum(losing)) if losing and sum(losing) != 0 else float("inf")

        return {
            "total_pnl": round(total_pnl, 2),
            "total_return_pct": round(total_return * 100, 2),
            "num_trades": len(pnls),
            "win_rate": round(win_rate, 4),
            "profit_factor": round(profit_factor, 4),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "largest_win": round(max(pnls), 2) if pnls else 0,
            "largest_loss": round(min(pnls), 2) if pnls else 0,
        }

    @staticmethod
    def compute_ic(
        predictions: np.ndarray,
        actual: np.ndarray,
    ) -> dict[str, float]:
        """Compute Information Coefficient.

        Args:
            predictions: Predicted returns.
            actual: Realized returns.

        Returns:
            IC metrics.
        """
        valid = ~(np.isnan(predictions) | np.isnan(actual))
        if valid.sum() < 10:
            return {"ic": 0.0, "rank_ic": 0.0}

        # Pearson IC
        pearson = float(np.corrcoef(predictions[valid], actual[valid])[0, 1])

        # Rank IC (Spearman)
        from scipy.stats import spearmanr
        rank_ic, _ = spearmanr(predictions[valid], actual[valid])

        return {
            "ic": round(pearson if not np.isnan(pearson) else 0.0, 6),
            "rank_ic": round(float(rank_ic) if not np.isnan(rank_ic) else 0.0, 6),
        }
