"""services/risk_service/api/portfolio_analytics.py – Portfolio analytics endpoints.

Endpoints:
- GET /portfolio-history – NAV history and cumulative returns
- GET /yearly-returns – Annual return aggregation
- GET /drawdown-history – Drawdown timeline from NAV sequence
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from sqlalchemy import text

from shared.database.engine import get_engine
from shared.core.logger import get_logger
from shared.schema import APIResponse

router = APIRouter()


def _safe_float(value, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@router.get("/portfolio-history")
async def portfolio_history(
    days: int = Query(default=90, ge=1, le=3650, description="Number of days of history"),
) -> APIResponse:
    """Get portfolio NAV history and cumulative returns.

    Queries the ``portfolios`` table for the latest *days* snapshots.

    Args:
        days: Number of calendar days to retrieve (max 3650).

    Returns:
        NAV time series and cumulative return values.
    """
    log = get_logger(__name__)
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT snapshot_date, nav, daily_return, cumulative_return
                    FROM portfolios
                    ORDER BY snapshot_date DESC
                    LIMIT :days
                    """
                ),
                {"days": days},
            )
            rows = result.fetchall()

        if not rows:
            return APIResponse(
                success=True,
                message="No portfolio history available",
                data={"nav_history": [], "cumulative_returns": [], "count": 0},
            )

        # Reverse to chronological order
        rows_reversed = list(reversed(rows))

        nav_history: list[dict] = []
        cumulative_returns: list[dict] = []
        daily_returns: list[float] = []

        for row in rows_reversed:
            dt = row[0]
            date_str = dt.isoformat() if isinstance(dt, date) else str(dt)
            nav = _safe_float(row[1])
            daily_ret = _safe_float(row[3])

            nav_history.append({"date": date_str, "nav": nav})
            cumulative_returns.append({"date": date_str, "cumulative_return": daily_ret})
            daily_returns.append(daily_ret)

        # Compute simple summary stats
        start_nav = nav_history[0]["nav"] if nav_history else 0.0
        end_nav = nav_history[-1]["nav"] if nav_history else 0.0
        total_return = ((end_nav - start_nav) / start_nav) if start_nav > 0 else 0.0

        # Sharpe from daily returns
        if len(daily_returns) >= 20:
            ret_arr = np.array(daily_returns)
            mean_ret = float(np.mean(ret_arr))
            std_ret = float(np.std(ret_arr, ddof=1))
            sharpe = round(mean_ret / std_ret * np.sqrt(252), 4) if std_ret > 0 else 0.0
        else:
            sharpe = 0.0

        return APIResponse(
            success=True,
            message=f"Portfolio history: {len(rows)} days, "
            f"return={total_return:.2%}, sharpe={sharpe}",
            data={
                "nav_history": nav_history,
                "cumulative_returns": cumulative_returns,
                "count": len(rows),
                "summary": {
                    "start_date": nav_history[0]["date"] if nav_history else None,
                    "end_date": nav_history[-1]["date"] if nav_history else None,
                    "start_nav": round(start_nav, 2),
                    "end_nav": round(end_nav, 2),
                    "total_return": round(total_return, 6),
                    "sharpe_ratio": sharpe,
                },
            },
        )
    except Exception as e:
        # Fresh Windows/SQLite paper deploys may not have tables yet.
        msg = str(e).lower()
        if "no such table" in msg or "does not exist" in msg:
            log.warning(f"portfolio history unavailable (empty schema): {e}")
            return APIResponse(
                success=True,
                message="No portfolio history available",
                data={"nav_history": [], "cumulative_returns": [], "count": 0},
            )
        log.exception(f"Failed to retrieve portfolio history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/yearly-returns")
async def yearly_returns(
    year: int = Query(default=2025, ge=2000, le=2100, description="Calendar year"),
) -> APIResponse:
    """Get annual return aggregation for a specific year.

    Args:
        year: Calendar year to query.

    Returns:
        Annual return, monthly breakdown, and trading-day count.
    """
    log = get_logger(__name__)
    try:
        start_dt = date(year, 1, 1)
        end_dt = date(year, 12, 31)

        engine = get_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT snapshot_date, nav, daily_return
                    FROM portfolios
                    WHERE snapshot_date BETWEEN :start AND :end
                    ORDER BY snapshot_date ASC
                    """
                ),
                {"start": start_dt, "end": end_dt},
            )
            rows = result.fetchall()

        if not rows:
            return APIResponse(
                success=True,
                message=f"No data for year {year}",
                data={"year": year, "annual_return": None, "monthly_returns": {}},
            )

        # Compute annual return from first to last NAV
        first_nav = _safe_float(rows[0][1])
        last_nav = _safe_float(rows[-1][1])
        annual_return = (
            round((last_nav - first_nav) / first_nav, 6) if first_nav > 0 else 0.0
        )

        # Monthly breakdown
        monthly_returns: dict[str, float] = {}
        for row in rows:
            dt = row[0] if isinstance(row[0], date) else datetime.strptime(str(row[0]), "%Y-%m-%d").date()
            month_key = dt.strftime("%Y-%m")
            if month_key not in monthly_returns:
                monthly_returns[month_key] = _safe_float(row[2], 0.0)
            else:
                # Compound within month
                monthly_returns[month_key] = (1 + monthly_returns[month_key]) * (1 + _safe_float(row[2], 0.0)) - 1

        return APIResponse(
            success=True,
            message=f"Year {year}: {annual_return:.2%} return over {len(rows)} trading days",
            data={
                "year": year,
                "annual_return": annual_return,
                "trading_days": len(rows),
                "monthly_returns": monthly_returns,
            },
        )
    except Exception as e:
        log.exception(f"Failed to retrieve yearly returns: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/drawdown-history")
async def drawdown_history(
    days: int = Query(default=365, ge=1, le=3650, description="Number of days"),
) -> APIResponse:
    """Compute portfolio-level drawdown timeline from the NAV sequence.

    Calculates rolling peak-to-trough drawdowns from the daily NAV values.

    Args:
        days: Number of calendar days to analyze.

    Returns:
        Drawdown time series, max drawdown, and current drawdown.
    """
    log = get_logger(__name__)
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT snapshot_date, nav
                    FROM portfolios
                    ORDER BY snapshot_date ASC
                    """
                ),
            )
            rows = result.fetchall()

        if not rows:
            return APIResponse(
                success=True,
                message="No portfolio data for drawdown analysis",
                data={"drawdown_series": [], "max_drawdown": 0.0, "current_drawdown": 0.0},
            )

        # Compute drawdowns
        nav_values = np.array([_safe_float(r[1]) for r in rows])
        dates = [
            r[0].isoformat() if isinstance(r[0], date) else str(r[0])
            for r in rows
        ]

        peak = np.maximum.accumulate(nav_values)
        drawdowns = (peak - nav_values) / peak

        drawdown_series: list[dict] = []
        for i in range(len(dates)):
            drawdown_series.append({
                "date": dates[i],
                "nav": round(float(nav_values[i]), 2),
                "drawdown": round(float(drawdowns[i]), 6),
                "peak": round(float(peak[i]), 2),
            })

        # Take last `days` entries
        drawdown_series = drawdown_series[-days:]

        max_dd = round(float(np.max(drawdowns[-days:])), 6) if len(drawdowns) > 0 else 0.0
        current_dd = round(float(drawdowns[-1]), 6) if len(drawdowns) > 0 else 0.0

        # Dates for max drawdown
        max_idx = int(np.argmax(drawdowns[-days:]))
        peak_date = dates[-(days - max_idx)] if max_idx < len(drawdown_series) else None

        return APIResponse(
            success=True,
            message=f"Drawdown history: max={max_dd:.2%}, current={current_dd:.2%}",
            data={
                "drawdown_series": drawdown_series,
                "max_drawdown": max_dd,
                "current_drawdown": current_dd,
                "max_drawdown_date": peak_date,
                "count": len(drawdown_series),
            },
        )
    except Exception as e:
        log.exception(f"Failed to compute drawdown history: {e}")
        raise HTTPException(status_code=500, detail=str(e))
