"""api_gateway/routes/dashboard.py – Dashboard aggregation endpoint.

GET /api/v2/dashboard
Returns a unified DashboardResponse aggregating portfolio,
trade, and risk metrics from the database with graceful degradation.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
from fastapi import APIRouter
from loguru import logger
from sqlalchemy import text

from shared.database.engine import get_engine
from shared.schema import APIResponse
from shared.schemas.dashboard import DashboardResponse

router = APIRouter()


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert a value to float, returning default on failure."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    """Convert a value to int, returning default on failure."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@router.get("/dashboard", response_model=APIResponse[DashboardResponse])
async def dashboard() -> APIResponse[DashboardResponse]:
    """Aggregate dashboard metrics from portfolios and trades tables.

    Computes Sharpe ratio, MaxDD, Calmar ratio, win rate, profit factor,
    and time-series NAV/P&L snapshots. Returns a degraded response
    with estimated values if the database is unavailable.
    """
    engine = get_engine()
    degraded = False

    try:
        async with engine.connect() as conn:
            # ── Latest portfolio snapshot ────────────────────
            pf_result = await conn.execute(
                text(
                    """
                    SELECT nav, cash, daily_pnl, daily_return,
                           sharpe_ratio, max_drawdown, num_positions
                    FROM portfolios
                    ORDER BY snapshot_date DESC
                    LIMIT 1
                    """
                )
            )
            pf_row = pf_result.fetchone()

            # ── Trade stats ──────────────────────────────────
            trade_result = await conn.execute(
                text(
                    """
                    SELECT
                        COUNT(*) AS total_trades,
                        COUNT(CASE WHEN side IN ('SELL', 'SELL_SHORT', 'COVER')
                              THEN 1 END) AS completed_trades
                    FROM trades
                    """
                )
            )
            t_row = trade_result.fetchone()

            total_trades = _safe_int(t_row[0]) if t_row else 0

            # ── Win rate & profit factor from completed trades ─
            # Approximate P&L for SELL/COVER side trades:
            #   pnl = notional - (quantity * price + commission)
            # Positive → win; negative → loss
            if total_trades > 0:
                wl_result = await conn.execute(
                    text(
                        """
                        SELECT
                            COUNT(CASE WHEN (notional - (quantity * price + commission)) > 0
                                  THEN 1 END) AS wins,
                            COUNT(CASE WHEN (notional - (quantity * price + commission)) < 0
                                  THEN 1 END) AS losses,
                            SUM(CASE WHEN (notional - (quantity * price + commission)) > 0
                                THEN (notional - (quantity * price + commission)) ELSE 0 END) AS gross_profit,
                            SUM(CASE WHEN (notional - (quantity * price + commission)) < 0
                                THEN ((quantity * price + commission) - notional) ELSE 0 END) AS gross_loss
                        FROM trades
                        WHERE side IN ('SELL', 'SELL_SHORT', 'COVER')
                        """
                    )
                )
                wl_row = wl_result.fetchone()
                wins = _safe_int(wl_row[0]) if wl_row else 0
                losses = _safe_int(wl_row[1]) if wl_row else 0
                completed = wins + losses
                win_rate = round(wins / completed, 4) if completed > 0 else 0.0

                gross_profit = _safe_float(wl_row[2]) if wl_row else 0.0
                gross_loss = _safe_float(wl_row[3]) if wl_row else 0.0
                profit_factor = (
                    round(gross_profit / gross_loss, 4) if gross_loss > 0 else 999.0
                )
            else:
                win_rate = 0.0
                profit_factor = 0.0

            # ── NAV / P&L snapshots (last 252 days) ─────────
            nav_result = await conn.execute(
                text(
                    """
                    SELECT snapshot_date, nav, daily_pnl, daily_return
                    FROM portfolios
                    ORDER BY snapshot_date DESC
                    LIMIT 252
                    """
                )
            )
            nav_rows = nav_result.fetchall()

            nav_snapshots: list[dict] = []
            pnl_snapshots: list[dict] = []
            daily_returns: list[float] = []

            for row in reversed(nav_rows):
                nav_snapshots.append(
                    {
                        "date": row[0].isoformat() if isinstance(row[0], date) else str(row[0]),
                        "nav": _safe_float(row[1]),
                    }
                )
                pnl_snapshots.append(
                    {
                        "date": row[0].isoformat() if isinstance(row[0], date) else str(row[0]),
                        "pnl": _safe_float(row[2]),
                    }
                )
                daily_returns.append(_safe_float(row[3]))

            # ── Metrics from latest portfolio row ────────────
            if pf_row:
                total_asset = _safe_float(pf_row[0])
                cash = _safe_float(pf_row[1])
                pnl = _safe_float(pf_row[2])
                pnl_pct = _safe_float(pf_row[3])
                sharpe_ratio = _safe_float(pf_row[4])
                max_drawdown = abs(_safe_float(pf_row[5]))
                positions = _safe_int(pf_row[6])
            else:
                total_asset = 0.0
                cash = 0.0
                pnl = 0.0
                pnl_pct = 0.0
                sharpe_ratio = 0.0
                max_drawdown = 0.0
                positions = 0

            # ── Compute Sharpe from daily returns if missing ─
            if sharpe_ratio == 0.0 and len(daily_returns) >= 20:
                ret_arr = np.array(daily_returns)
                mean_ret = float(np.mean(ret_arr))
                std_ret = float(np.std(ret_arr, ddof=1))
                if std_ret > 0:
                    sharpe_ratio = round(mean_ret / std_ret * np.sqrt(252), 4)

            # ── Compute MaxDD from NAV if missing ────────────
            if max_drawdown == 0.0 and len(nav_snapshots) >= 20:
                nav_values = np.array([s["nav"] for s in nav_snapshots])
                peak = np.maximum.accumulate(nav_values)
                drawdowns = (peak - nav_values) / peak
                max_drawdown = round(float(np.max(drawdowns)), 4) if len(drawdowns) > 0 else 0.0

            # ── Compute Calmar ratio ─────────────────────────
            if max_drawdown > 0 and len(daily_returns) >= 20:
                ann_return = float(np.mean(daily_returns)) * 252
                calmar_ratio = round(ann_return / max_drawdown, 4)
            else:
                calmar_ratio = 0.0

            return APIResponse(
                success=True,
                message="Dashboard metrics aggregated",
                data=DashboardResponse(
                    sharpe_ratio=sharpe_ratio,
                    max_drawdown=max_drawdown,
                    win_rate=win_rate,
                    profit_factor=profit_factor,
                    calmar_ratio=calmar_ratio,
                    total_asset=total_asset,
                    cash=cash,
                    pnl=pnl,
                    pnl_pct=pnl_pct,
                    positions=positions,
                    total_trades=total_trades,
                    nav_snapshots=nav_snapshots,
                    pnl_snapshots=pnl_snapshots,
                ),
            )

    except Exception as exc:
        degraded = True
        logger.warning(f"Dashboard aggregation failed (degraded mode): {exc}")

    # ── Degraded fallback ────────────────────────────────────
    return APIResponse(
        success=True,
        message="Dashboard metrics (degraded — database unavailable)",
        code="DEGRADED",
        data=DashboardResponse(
            sharpe_ratio=0.0,
            max_drawdown=0.0,
            win_rate=0.0,
            profit_factor=0.0,
            calmar_ratio=0.0,
            total_asset=0.0,
            cash=0.0,
            pnl=0.0,
            pnl_pct=0.0,
            positions=0,
            total_trades=0,
            nav_snapshots=[],
            pnl_snapshots=[],
        ),
    )
