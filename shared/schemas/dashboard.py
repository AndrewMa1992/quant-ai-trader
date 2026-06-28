"""shared/schemas/dashboard.py – Dashboard aggregation response models.

Provides the unified DashboardResponse model consumed by the
GET /api/v2/dashboard endpoint in the API gateway.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DashboardResponse(BaseModel):
    """Aggregated dashboard metrics for portfolio overview.

    Computed from portfolios and trades tables with simplified
    Sharpe/Calmar/MaxDD approximations (252-day basis).
    """

    sharpe_ratio: float = Field(
        default=0.0,
        description="Annualized Sharpe ratio computed from 252-day daily returns",
    )
    max_drawdown: float = Field(
        default=0.0,
        description="Maximum peak-to-trough drawdown as a non-negative fraction",
    )
    win_rate: float = Field(
        default=0.0,
        description="Fraction of completed round-trip trades with positive P&L",
    )
    profit_factor: float = Field(
        default=0.0,
        description="Gross profit divided by gross loss across all trades",
    )
    calmar_ratio: float = Field(
        default=0.0,
        description="Annualized return divided by max drawdown",
    )
    total_asset: float = Field(
        default=0.0,
        description="Total portfolio net asset value (NAV)",
    )
    cash: float = Field(
        default=0.0,
        description="Cash balance",
    )
    pnl: float = Field(
        default=0.0,
        description="Most recent daily P&L",
    )
    pnl_pct: float = Field(
        default=0.0,
        description="Most recent daily return as a fraction",
    )
    positions: int = Field(
        default=0,
        description="Number of open positions",
    )
    total_trades: int = Field(
        default=0,
        description="Total number of executed trades in the database",
    )
    nav_snapshots: list[dict] = Field(
        default_factory=list,
        description="Daily NAV time series for the last 252 days",
    )
    pnl_snapshots: list[dict] = Field(
        default_factory=list,
        description="Daily P&L time series for the last 252 days",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "sharpe_ratio": 1.25,
                "max_drawdown": 0.12,
                "win_rate": 0.58,
                "profit_factor": 1.8,
                "calmar_ratio": 2.1,
                "total_asset": 1250000.0,
                "cash": 150000.0,
                "pnl": 5200.0,
                "pnl_pct": 0.0042,
                "positions": 12,
                "total_trades": 340,
                "nav_snapshots": [],
                "pnl_snapshots": [],
            }
        }
    }
