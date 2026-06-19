"""services/risk_service/stress_test/custom_scenarios.py – Custom stress scenarios.

Configurable shocks:
- ±10% / ±20% equity index shock
- VIX spike (+50% / +100% / +200%)
- Interest rate ±200bp
- Sector rotation
- Correlation breakdown
"""

from __future__ import annotations

from typing import Any

import numpy as np
from loguru import logger


class CustomScenarioEngine:
    """Applies user-defined or parameterized stress scenarios."""

    PRESETS: dict[str, dict[str, Any]] = {
        "market_crash_10": {"equity_shock": -0.10, "rate_change": 0, "vix_change_pct": 0.5},
        "market_crash_20": {"equity_shock": -0.20, "rate_change": 0, "vix_change_pct": 1.0},
        "market_rally_10": {"equity_shock": 0.10, "rate_change": 0, "vix_change_pct": -0.25},
        "market_rally_20": {"equity_shock": 0.20, "rate_change": 0, "vix_change_pct": -0.40},
        "vix_spike_50": {"equity_shock": -0.05, "rate_change": 0, "vix_change_pct": 0.50},
        "vix_spike_100": {"equity_shock": -0.10, "rate_change": 0, "vix_change_pct": 1.00},
        "vix_spike_200": {"equity_shock": -0.15, "rate_change": 0, "vix_change_pct": 2.00},
        "rate_up_200bp": {"equity_shock": -0.08, "rate_change": 200, "vix_change_pct": 0.25},
        "rate_down_200bp": {"equity_shock": 0.05, "rate_change": -200, "vix_change_pct": -0.15},
        "sector_rotation": {"equity_shock": 0.0, "rate_change": 0, "vix_change_pct": 0.1,
                             "sector_rotation": True},
        "correlation_breakdown": {"equity_shock": -0.05, "rate_change": 0, "vix_change_pct": 0.3,
                                   "correlation_multiplier": 2.0},
    }

    def run(
        self,
        scenario_key: str,
        tickers: list[str],
        weights: list[float],
    ) -> dict[str, Any]:
        """Execute a custom stress scenario.

        Args:
            scenario_key: Preset key or custom param string.
            tickers: Portfolio tickers.
            weights: Portfolio weights.

        Returns:
            Stress test result.
        """
        params = self.PRESETS.get(scenario_key, {
            "equity_shock": -0.10,
            "rate_change": 0,
            "vix_change_pct": 0.5,
        })

        equity_shock = float(params.get("equity_shock", 0))
        vix_change = float(params.get("vix_change_pct", 0))
        rate_change = float(params.get("rate_change", 0))
        corr_mult = float(params.get("correlation_multiplier", 1.0))
        sector_rotation = bool(params.get("sector_rotation", False))

        # Asset class sensitivity coefficients
        equity_beta = 1.0
        bond_duration_approx = 6.0  # ~6 year duration
        bond_shock = -rate_change * 0.0001 * bond_duration_approx

        # Composite shock per asset
        composite_shocks: dict[str, float] = {}
        for i, ticker in enumerate(tickers):
            # Simplified: assume all are equities with beta ~1
            ticker_shock = equity_shock * equity_beta
            if sector_rotation:
                # Half the portfolio gets +rotation, half gets -rotation
                ticker_shock += (0.05 if i % 2 == 0 else -0.05)
            composite_shocks[ticker] = float(ticker_shock)

        # Portfolio-level
        portfolio_shock = sum(w * composite_shocks[t] for t, w in zip(tickers, weights))
        # Scale correlation impact
        effective_shock = portfolio_shock * (1.0 + 0.1 * (corr_mult - 1.0))

        return {
            "scenario": scenario_key,
            "portfolio_loss": round(float(effective_shock), 6),
            "portfolio_loss_pct": round(float(effective_shock) * 100, 2),
            "parameters": params,
            "ticker_shocks": composite_shocks,
            "bond_impact": round(bond_shock, 6),
        }


custom_scenario_engine = CustomScenarioEngine()
