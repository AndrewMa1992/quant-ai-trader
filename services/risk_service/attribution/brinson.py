"""services/risk_service/attribution/brinson.py – Brinson performance attribution.

Decomposes excess return into:
- Allocation effect: (w_portfolio - w_benchmark) * R_benchmark_sector
- Selection effect: w_benchmark * (R_portfolio_sector - R_benchmark_sector)
- Interaction effect: (w_portfolio - w_benchmark) * (R_portfolio_sector - R_benchmark_sector)
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from services.data_service.storage.parquet_store import ParquetStore


class BrinsonAttribution:
    """Brinson performance attribution model.

    Decomposes portfolio return relative to benchmark into:
    - Allocation: decisions about which sectors/markets to overweight
    - Selection: stock picking within sectors
    - Interaction: cross-product of allocation and selection
    """

    def __init__(self) -> None:
        self._store = ParquetStore()

    def attribute(
        self,
        tickers: list[str],
        weights: list[float],
        benchmark_ticker: str = "SPY",
    ) -> dict[str, Any]:
        """Run Brinson attribution.

        Args:
            tickers: Portfolio tickers.
            weights: Portfolio weights.
            benchmark_ticker: Benchmark symbol.

        Returns:
            Attribution breakdown.
        """
        portfolio_return = self._compute_return(tickers, weights)
        benchmark_return = self._compute_return([benchmark_ticker], [1.0])

        excess_return = portfolio_return - benchmark_return

        # Simplified sector-based attribution
        sectors = self._get_ticker_sectors(tickers)
        sector_returns = self._get_sector_returns(sectors)

        allocation_effect = 0.0
        selection_effect = 0.0
        interaction_effect = 0.0

        sector_details: dict[str, dict[str, float]] = {}

        for sector in set(sectors.values()):
            sector_tickers = [t for t, s in sectors.items() if s == sector]
            sector_indices = [i for i, t in enumerate(tickers) if t in sector_tickers]

            w_port = sum(weights[i] for i in sector_indices)
            w_bench = 1.0 / max(len(set(sectors.values())), 1)  # Equal-weight benchmark

            r_port_sector = float(np.mean([self._compute_return([t], [1.0]) for t in sector_tickers]))
            r_bench_sector = sector_returns.get(sector, benchmark_return)

            alloc = (w_port - w_bench) * r_bench_sector
            sel = w_bench * (r_port_sector - r_bench_sector)
            inter = (w_port - w_bench) * (r_port_sector - r_bench_sector)

            allocation_effect += alloc
            selection_effect += sel
            interaction_effect += inter

            sector_details[sector] = {
                "allocation_effect": round(alloc, 6),
                "selection_effect": round(sel, 6),
                "interaction_effect": round(inter, 6),
                "portfolio_weight": round(w_port, 4),
            }

        return {
            "portfolio_return": round(portfolio_return, 6),
            "benchmark_return": round(benchmark_return, 6),
            "excess_return": round(excess_return, 6),
            "allocation_effect": round(allocation_effect, 6),
            "selection_effect": round(selection_effect, 6),
            "interaction_effect": round(interaction_effect, 6),
            "sector_details": sector_details,
        }

    def _compute_return(self, tickers: list[str], weights: list[float]) -> float:
        """Compute weighted portfolio return over most recent period."""
        rets = []
        for ticker in tickers:
            df = self._store.read_daily(ticker)
            if df is None or len(df) < 5:
                return 0.0
            col = "adj_close" if "adj_close" in df.columns else "close"
            ret = float(df[col].pct_change(21).iloc[-1])  # Monthly return
            rets.append(ret if np.isfinite(ret) else 0.0)

        if not rets:
            return 0.0
        return float(np.dot(rets, weights[:len(rets)]))

    def _get_ticker_sectors(self, tickers: list[str]) -> dict[str, str]:
        """Get sector mapping (simplified — uses ETF proxies)."""
        # Default sector mapping
        sector_map = {
            "XLK": "Technology", "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology",
            "XLF": "Financial", "JPM": "Financial", "BAC": "Financial", "GS": "Financial",
            "XLV": "Healthcare", "JNJ": "Healthcare", "UNH": "Healthcare", "PFE": "Healthcare",
            "XLE": "Energy", "XOM": "Energy", "CVX": "Energy",
            "XLY": "Consumer", "AMZN": "Consumer", "TSLA": "Consumer", "HD": "Consumer",
            "XLI": "Industrial", "CAT": "Industrial", "BA": "Industrial",
            "XLU": "Utilities", "SO": "Utilities", "DUK": "Utilities",
        }
        result: dict[str, str] = {}
        for t in tickers:
            result[t] = sector_map.get(t, "Other")
        return result

    def _get_sector_returns(self, sectors: dict[str, str]) -> dict[str, float]:
        """Get returns for sectors (simplified)."""
        returns: dict[str, float] = {
            "Technology": 0.02, "Financial": 0.01, "Healthcare": 0.005,
            "Energy": -0.01, "Consumer": 0.015, "Industrial": 0.01,
            "Utilities": 0.003, "Other": 0.008,
        }
        return returns
