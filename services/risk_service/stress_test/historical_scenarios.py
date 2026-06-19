"""services/risk_service/stress_test/historical_scenarios.py – Historical stress scenarios.

5 pre-defined historical crisis scenarios:
1. 2008 Financial Crisis (Sep-Dec 2008)
2. 2020 COVID Crash (Feb-Mar 2020)
3. 2022 Rate Hike (Jan-Oct 2022)
4. 2018 Vol Spike (Feb 2018)
5. 2015 China Crash (Jun-Aug 2015)
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

SCENARIO_DEFINITIONS: dict[str, dict[str, Any]] = {
    "crisis_2008": {
        "name": "2008 Financial Crisis",
        "description": "Lehman collapse, global financial meltdown",
        "equity_shock": -0.35,
        "bond_shock": 0.05,
        "vix_multiplier": 4.0,
        "correlation_shock": 1.2,
        "liquidity_discount": 0.3,
        "rate_change_bps": -200,
    },
    "covid_2020": {
        "name": "2020 COVID-19 Crash",
        "description": "Global pandemic, rapid market sell-off",
        "equity_shock": -0.30,
        "bond_shock": 0.02,
        "vix_multiplier": 3.5,
        "correlation_shock": 1.3,
        "liquidity_discount": 0.25,
        "rate_change_bps": -150,
    },
    "rate_hike_2022": {
        "name": "2022 Fed Rate Hike Cycle",
        "description": "Aggressive Fed tightening, tech sell-off",
        "equity_shock": -0.20,
        "bond_shock": -0.15,
        "vix_multiplier": 2.0,
        "correlation_shock": 1.1,
        "liquidity_discount": 0.1,
        "rate_change_bps": 400,
    },
    "vol_spike_2018": {
        "name": "2018 Volmageddon",
        "description": "VIX explosion, short-vol strategies unwind",
        "equity_shock": -0.10,
        "bond_shock": 0.03,
        "vix_multiplier": 5.0,
        "correlation_shock": 1.15,
        "liquidity_discount": 0.2,
        "rate_change_bps": 0,
    },
    "china_crash_2015": {
        "name": "2015 China Stock Market Crash",
        "description": "A-share bubble burst, circuit breakers",
        "equity_shock": -0.40,
        "bond_shock": 0.01,
        "vix_multiplier": 3.0,
        "correlation_shock": 1.1,
        "liquidity_discount": 0.4,
        "rate_change_bps": -100,
    },
}


class HistoricalScenarioEngine:
    """Runs historical stress scenarios on portfolios."""

    @staticmethod
    def run(
        scenario_name: str,
        tickers: list[str],
        weights: list[float],
    ) -> dict[str, Any]:
        """Apply historical scenario shocks to a portfolio.

        Args:
            scenario_name: One of the predefined scenario keys.
            tickers: Portfolio ticker symbols.
            weights: Portfolio weights.

        Returns:
            Stress test result dictionary.
        """
        scenario = SCENARIO_DEFINITIONS.get(scenario_name)
        if scenario is None:
            return {"error": f"Unknown scenario: {scenario_name}", "available": list(SCENARIO_DEFINITIONS.keys())}

        # Portfolio-level impact
        equity_shock = float(scenario["equity_shock"])
        liquidity_discount = float(scenario["liquidity_discount"])

        # Weighted portfolio loss
        portfolio_loss = sum(w * equity_shock for w in weights)
        # Additional liquidity haircut on stressed assets
        portfolio_loss *= (1.0 + liquidity_discount)

        # Estimated individual ticker impacts
        ticker_impacts: dict[str, dict[str, float]] = {}
        for i, ticker in enumerate(tickers):
            # Beta-based adjustment
            ticker_beta = 1.0 + i * 0.1  # Simplified
            ticker_loss = equity_shock * ticker_beta * (1.0 + liquidity_discount)
            ticker_impacts[ticker] = {
                "estimated_loss": round(ticker_loss, 4),
                "estimated_loss_pct": round(ticker_loss * 100, 2),
            }

        return {
            "scenario": scenario["name"],
            "description": scenario["description"],
            "portfolio_loss": round(portfolio_loss, 6),
            "portfolio_loss_pct": round(portfolio_loss * 100, 2),
            "vix_multiplier": scenario["vix_multiplier"],
            "rate_change_bps": scenario["rate_change_bps"],
            "ticker_impacts": ticker_impacts,
            "parameters": {k: v for k, v in scenario.items() if k not in ("name", "description")},
        }


historical_scenario_engine = HistoricalScenarioEngine()
