"""Capital-aware trading policy for small paper accounts (e.g. $1700).

Single source of truth for min trade size, position caps, and deploy fraction.
Top funds size risk to NAV — retail capital must not inherit $100k floors.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CapitalPolicy:
    nav: float
    min_trade_value: float
    max_position_frac: float
    max_cash_usage: float
    deploy_frac: float  # total equity target for equal-weight fallback
    max_daily_trades: int
    buy_strength_cap: float


def build_capital_policy(nav: float) -> CapitalPolicy:
    """Derive trade constraints from current NAV."""
    nav = max(float(nav), 1.0)
    if nav < 5_000:
        # Micro account (~$1700): allow small tickets, higher single-name weight
        return CapitalPolicy(
            nav=nav,
            min_trade_value=max(25.0, min(75.0, nav * 0.03)),
            max_position_frac=0.35,
            max_cash_usage=0.95,
            deploy_frac=0.85,
            max_daily_trades=24,
            buy_strength_cap=0.35,
        )
    if nav < 50_000:
        return CapitalPolicy(
            nav=nav,
            min_trade_value=max(50.0, min(200.0, nav * 0.02)),
            max_position_frac=0.25,
            max_cash_usage=0.95,
            deploy_frac=0.80,
            max_daily_trades=20,
            buy_strength_cap=0.25,
        )
    return CapitalPolicy(
        nav=nav,
        min_trade_value=100.0,
        max_position_frac=0.20,
        max_cash_usage=0.95,
        deploy_frac=0.70,
        max_daily_trades=40,
        buy_strength_cap=0.20,
    )
