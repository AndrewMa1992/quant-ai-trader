"""services/risk_service/api/signal_routes.py – Signal history endpoints.

Endpoints:
- GET /signals – Trading signal history with pagination
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from sqlalchemy import text

from shared.database.engine import get_engine
from shared.core.logger import get_logger
from shared.schema import APIResponse

router = APIRouter()


def _safe_float(value, default: float = 0.0) -> float:
    """Convert value to float with a safe default."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default: int = 0) -> int:
    """Convert value to int with a safe default."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@router.get("/signals")
async def get_signals(
    ticker: str | None = Query(default=None, description="Filter by ticker symbol"),
    limit: int = Query(default=100, ge=1, le=1000, description="Max signals to return"),
    since: str | None = Query(default=None, description="ISO date filter (YYYY-MM-DD)"),
    direction: int | None = Query(default=None, description="Filter: 1=LONG, -1=SHORT, 0=FLAT"),
) -> APIResponse:
    """Query historical trading signals from the ``signals`` table.

    Supports optional filtering by ticker, date range, and direction.

    Args:
        ticker: Optional ticker filter.
        limit: Maximum number of signals to return.
        since: Return signals on or after this date.
        direction: Filter by signal direction (1, -1, 0).

    Returns:
        APIResponse with signals list and count.
    """
    log = get_logger(__name__)
    try:
        conditions: list[str] = ["1=1"]
        params: dict = {"limit": limit}

        if ticker:
            conditions.append("ticker = :ticker")
            params["ticker"] = ticker.upper()

        if since:
            try:
                since_date = date.fromisoformat(since)
                conditions.append("signal_date >= :since")
                params["since"] = since_date
            except (ValueError, TypeError):
                pass

        if direction is not None:
            conditions.append("direction = :direction")
            params["direction"] = direction

        where_clause = " AND ".join(conditions)
        query = f"""
            SELECT ticker, signal_date, horizon, direction, strength,
                   target_weight, predicted_return, confidence,
                   risk_score, is_executed, created_at
            FROM signals
            WHERE {where_clause}
            ORDER BY signal_date DESC, ticker ASC
            LIMIT :limit
        """

        engine = get_engine()
        async with engine.connect() as conn:
            result = await conn.execute(text(query), params)
            rows = result.fetchall()

        signals: list[dict] = []
        for row in rows:
            signals.append({
                "ticker": row[0],
                "signal_date": row[1].isoformat() if isinstance(row[1], date) else str(row[1]),
                "horizon": row[2],
                "direction": _safe_int(row[3]),
                "direction_label": (
                    "LONG" if row[3] == 1 else "SHORT" if row[3] == -1 else "FLAT"
                ),
                "strength": _safe_float(row[4]),
                "target_weight": _safe_float(row[5]),
                "predicted_return": _safe_float(row[6]),
                "confidence": _safe_float(row[7]),
                "risk_score": _safe_float(row[8]),
                "is_executed": bool(row[9]) if row[9] is not None else False,
                "created_at": (
                    row[10].isoformat()
                    if isinstance(row[10], datetime) and row[10]
                    else str(row[10]) if row[10] else None
                ),
            })

        # Count total matching (without LIMIT)
        count_query = f"""
            SELECT COUNT(*) FROM signals WHERE {where_clause}
        """
        async with engine.connect() as conn:
            count_result = await conn.execute(text(count_query), params)
            total = count_result.scalar() or 0

        return APIResponse(
            success=True,
            message=f"Returned {len(signals)} signals (total: {total})",
            data={
                "signals": signals,
                "count": len(signals),
                "total": total,
                "limit": limit,
            },
        )
    except Exception as e:
        log.exception(f"Failed to query signals: {e}")
        raise HTTPException(status_code=500, detail=str(e))
