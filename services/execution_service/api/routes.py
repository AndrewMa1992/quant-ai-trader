"""services/execution_service/api/routes.py – Execution API endpoints.

Endpoints:
- POST /optimizer/markowitz – Mean-variance optimization
- POST /optimizer/bl – Black-Litterman optimization
- POST /backtest – Run event-driven backtest
- POST /order – Place a real or paper order (unified)
- POST /execute/order – Alias for POST /order (backward compatible)
- GET /order/{order_id} – Order status tracking
- GET /positions – Current positions
- GET /alerts – Recent alerts
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import text

from services.execution_service.api.schemas import OrderRequest, OrderResult
from services.execution_service.config import exec_config
from services.execution_service.optimizer.markowitz import MarkowitzOptimizer
from services.execution_service.optimizer.black_litterman import BlackLittermanOptimizer
from services.execution_service.optimizer.risk_parity import RiskParityOptimizer
from services.execution_service.backtest.event_engine import BacktestEngine
from services.execution_service.live.tiger_broker import TigerBroker
from services.execution_service.live.position_tracker import PositionTracker
from services.execution_service.live.circuit_breaker import CircuitBreaker
from services.execution_service.live.alert_manager import AlertManager
from services.execution_service.live.tiger_advanced import TigerAdvancedClient
from shared.core.logger import get_logger
from shared.database.engine import get_engine
from shared.schema import APIResponse

router = APIRouter()

# Service instances
_position_tracker = PositionTracker()
_circuit_breaker = CircuitBreaker()
_alert_manager = AlertManager()

# In-memory order cache + persistence path
_orders: dict[str, dict] = {}
_ORDERS_CACHE_PATH: Path = Path("cache") / "orders.jsonl"


class MarkowitzRequest(BaseModel):
    tickers: list[str] = Field(..., description="Universe tickers")
    objective: str = Field(default="max_sharpe", description="max_sharpe / min_risk / max_return")
    constraints: dict = Field(default_factory=dict)


class BLRequest(BaseModel):
    tickers: list[str] = Field(...)
    views: list[dict] = Field(default_factory=list, description="List of {ticker, return, confidence}")
    tau: float = Field(default=0.05, description="Uncertainty in prior")


class BacktestRequest(BaseModel):
    tickers: list[str] = Field(...)
    start_date: str = Field(default="2023-01-01")
    end_date: str = Field(default="2024-12-31")
    initial_capital: float = Field(default=1_000_000.0)


@router.post("/optimizer/markowitz")
async def optimize_markowitz(req: MarkowitzRequest) -> APIResponse:
    """Run mean-variance portfolio optimization."""
    log = get_logger(__name__)
    try:
        opt = MarkowitzOptimizer(objective=req.objective)
        result = opt.optimize(req.tickers, constraints=req.constraints)
        return APIResponse(success=True, message="MV optimization complete", data=result)
    except Exception as e:
        log.exception(f"MV optimization failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/optimizer/bl")
async def optimize_black_litterman(req: BLRequest) -> APIResponse:
    """Run Black-Litterman optimization."""
    log = get_logger(__name__)
    try:
        opt = BlackLittermanOptimizer(tau=req.tau)
        result = opt.optimize(req.tickers, req.views)
        return APIResponse(success=True, message="BL optimization complete", data=result)
    except Exception as e:
        log.exception(f"BL optimization failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/optimizer/risk_parity")
async def optimize_risk_parity(req: MarkowitzRequest) -> APIResponse:
    """Run Risk Parity optimization."""
    log = get_logger(__name__)
    try:
        opt = RiskParityOptimizer()
        result = opt.optimize(req.tickers)
        return APIResponse(success=True, message="Risk Parity complete", data=result)
    except Exception as e:
        log.exception(f"Risk Parity failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/backtest")
async def run_backtest(req: BacktestRequest, background_tasks: BackgroundTasks) -> APIResponse:
    """Run event-driven backtest."""
    log = get_logger(__name__)
    try:
        engine = BacktestEngine(
            tickers=req.tickers,
            start_date=req.start_date,
            end_date=req.end_date,
            initial_capital=req.initial_capital,
        )
        # Run synchronously for API demo; can be backgrounded
        result = engine.run()
        return APIResponse(
            success=True,
            message=f"Backtest: Sharpe={result.get('sharpe_ratio', 'N/A')}",
            data=result,
        )
    except Exception as e:
        log.exception(f"Backtest failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _persist_order(record: dict) -> None:
    """Append an order record to cache/orders.jsonl."""
    try:
        _ORDERS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_ORDERS_CACHE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"Failed to persist order to cache: {e}")


@router.post("/order", response_model=OrderResult)
async def place_order(req: OrderRequest) -> OrderResult:
    """Unified order placement endpoint — paper or live."""
    log = get_logger(__name__)

    order_id = str(uuid.uuid4())
    placed_at = time.time()

    # Build initial order record
    order_record = {
        "order_id": order_id,
        "ticker": req.ticker,
        "side": req.side,
        "quantity": req.quantity,
        "filled_price": None,
        "filled_qty": 0.0,
        "status": "queued",
        "algo": req.algo,
        "placed_at": placed_at,
        "updated_at": placed_at,
    }

    # Store in memory
    _orders[order_id] = order_record

    # Persist to JSON Lines
    _persist_order(order_record)

    try:
        # Circuit breaker check
        if not _circuit_breaker.allow_order(req.ticker, req.quantity):
            _orders[order_id]["status"] = "cancelled"
            _orders[order_id]["updated_at"] = time.time()
            _persist_order(_orders[order_id])
            return OrderResult(
                order_id=order_id,
                ticker=req.ticker,
                side=req.side,
                quantity=req.quantity,
                status="cancelled",
                algo=req.algo,
                placed_at=placed_at,
                updated_at=time.time(),
            )

        broker = TigerBroker(account=req.account or exec_config.TIGER_ACCOUNT)
        result = await broker.place_order(
            ticker=req.ticker,
            side=req.side,
            quantity=req.quantity,
            order_type=req.order_type,
            limit_price=req.limit_price,
            algo=req.algo,
        )

        # Update order record
        _orders[order_id]["filled_price"] = result.get("filled_price")
        _orders[order_id]["filled_qty"] = result.get("filled_qty", 0.0)
        _orders[order_id]["status"] = result.get("status", "submitted")
        _orders[order_id]["updated_at"] = time.time()
        _persist_order(_orders[order_id])

        # Update position tracker
        _position_tracker.record_order(result)

        # Check alert thresholds
        _alert_manager.check_and_alert(result)

        return OrderResult(
            order_id=order_id,
            ticker=req.ticker,
            side=req.side,
            quantity=req.quantity,
            filled_price=result.get("filled_price"),
            filled_qty=result.get("filled_qty", 0.0),
            status=result.get("status", "submitted"),
            algo=req.algo,
            placed_at=placed_at,
            updated_at=time.time(),
        )

    except HTTPException:
        _orders[order_id]["status"] = "cancelled"
        _orders[order_id]["updated_at"] = time.time()
        _persist_order(_orders[order_id])
        raise
    except Exception as e:
        log.exception(f"Order failed: {e}")
        _orders[order_id]["status"] = "cancelled"
        _orders[order_id]["updated_at"] = time.time()
        _persist_order(_orders[order_id])
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/order/{order_id}")
async def get_order_status(order_id: str) -> APIResponse:
    """Get the current status of an order by its ID.

    Checks the in-memory _orders dict first, then falls back to
    searching cache/orders.jsonl.
    """
    # Check in-memory cache first
    if order_id in _orders:
        return APIResponse(
            success=True,
            message=f"Order {order_id} status: {_orders[order_id].get('status')}",
            data=_orders[order_id],
        )

    # Fall back to orders.jsonl
    if _ORDERS_CACHE_PATH.exists():
        try:
            with open(_ORDERS_CACHE_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        if record.get("order_id") == order_id:
                            return APIResponse(
                                success=True,
                                message=f"Order {order_id} (from cache)",
                                data=record,
                            )
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.warning(f"Failed to read orders cache: {e}")

    return APIResponse(
        success=True,
        message="Order not found in cache",
        data={"order_id": order_id, "status": "unknown", "message": "Order not found in cache"},
    )


@router.post("/execute/order")
async def execute_order(req: OrderRequest) -> OrderResult:
    """Backward-compatible alias for POST /order.

    Delegates to the unified place_order handler.
    """
    return await place_order(req)


@router.get("/positions")
async def get_positions() -> APIResponse:
    """Get current positions."""
    try:
        positions = _position_tracker.get_positions()
        summary = _position_tracker.get_summary()
        return APIResponse(success=True, message=f"{len(positions)} positions", data={
            "positions": positions, "summary": summary,
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/alerts")
async def get_alerts(
    severity: str = Query(default="", description="Filter: INFO / WARN / CRITICAL"),
) -> APIResponse:
    """Get recent alerts."""
    try:
        alerts = _alert_manager.get_recent(severity=severity if severity else None)
        return APIResponse(success=True, message=f"{len(alerts)} alerts", data={"alerts": alerts})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── P1-1: Tiger Advanced Operations ───────────────────────────
_tiger_advanced = TigerAdvancedClient()


@router.post("/tiger/refresh-assets", tags=["Tiger Advanced"])
async def tiger_refresh_assets() -> APIResponse:
    """Pull current account assets from Tiger and update the DB.

    Fetches NAV, cash, and positions from Tiger Broker, then writes
    a new portfolio snapshot to the ``portfolios`` table.
    """
    try:
        result = await _tiger_advanced.refresh_assets()
        return APIResponse(
            success=result.get("status") == "success",
            message=f"Assets refreshed: NAV={result.get('nav', 0):,.0f}",
            data=result,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tiger/reconcile", tags=["Tiger Advanced"])
async def tiger_reconcile() -> APIResponse:
    """Reconcile Tiger positions against DB positions.

    Compares current Tiger Broker holdings with the latest records
    in the ``positions`` table and reports matches, deltas, and issues.
    """
    try:
        result = await _tiger_advanced.reconcile()
        summary = result.get("summary", {})
        return APIResponse(
            success=result.get("status") == "success",
            message=(
                f"Reconciliation: {summary.get('matched', 0)} matched, "
                f"{summary.get('deltas', 0)} deltas, "
                f"{summary.get('issues', 0)} issues"
            ),
            data=result,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tiger/repair-shorts", tags=["Tiger Advanced"])
async def tiger_repair_shorts() -> APIResponse:
    """Check short positions for borrowable share availability.

    Queries borrowable inventory for current short positions.
    Per architecture decision #4, this does NOT auto-place orders.
    """
    try:
        result = await _tiger_advanced.repair_shorts()
        return APIResponse(
            success=result.get("status") == "success",
            message=result.get("message", "Short repair check complete"),
            data=result,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tiger/account", tags=["Tiger Advanced"])
async def tiger_get_account() -> APIResponse:
    """Query full Tiger account information.

    Returns account status, permissions, funds, margin info,
    and currency settings.
    """
    try:
        result = await _tiger_advanced.get_account()
        return APIResponse(
            success=result.get("status") != "error",
            message=f"Account {result.get('account', 'unknown')} queried",
            data=result,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── P1-2: Order History ──────────────────────────────────────
@router.get("/orders", tags=["Orders"])
async def list_orders(
    ticker: str | None = Query(default=None, description="Filter by ticker"),
    limit: int = Query(default=50, ge=1, le=500, description="Max orders to return"),
    since: str | None = Query(default=None, description="ISO datetime filter"),
) -> APIResponse:
    """List historical orders from cache and DB.

    Merges results from ``cache/orders.jsonl`` (in-memory orders)
    and the ``trades`` database table. Supports optional ticker
    and date filtering with pagination.
    """
    log = get_logger(__name__)
    orders: list[dict] = []

    try:
        # ── In-memory orders ─────────────────────────────────
        for oid, orec in _orders.items():
            if ticker and orec.get("ticker", "").upper() != ticker.upper():
                continue
            if since:
                ts = orec.get("placed_at", 0)
                try:
                    since_ts = datetime.fromisoformat(since).timestamp()
                    if ts < since_ts:
                        continue
                except (ValueError, TypeError):
                    pass
            orders.append(orec)

        # ── Persisted orders (cache/orders.jsonl) ────────────
        if _ORDERS_CACHE_PATH.exists():
            try:
                with open(_ORDERS_CACHE_PATH, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                            oid = record.get("order_id", "")
                            # Skip if already in memory
                            if oid in _orders:
                                continue
                            if ticker and record.get("ticker", "").upper() != ticker.upper():
                                continue
                            if since:
                                ts = record.get("placed_at", 0)
                                try:
                                    since_ts = datetime.fromisoformat(since).timestamp()
                                    if ts < since_ts:
                                        continue
                                except (ValueError, TypeError):
                                    pass
                            orders.append(record)
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                log.warning(f"Failed to read orders cache: {e}")

        # ── DB trades ────────────────────────────────────────
        try:
            engine = get_engine()
            async with engine.connect() as conn:
                query = "SELECT * FROM trades"
                conditions: list[str] = []
                params: dict = {}

                if ticker:
                    conditions.append("ticker = :ticker")
                    params["ticker"] = ticker.upper()

                if since:
                    try:
                        since_dt = datetime.fromisoformat(since)
                        conditions.append("trade_time >= :since")
                        params["since"] = since_dt
                    except (ValueError, TypeError):
                        pass

                if conditions:
                    query += " WHERE " + " AND ".join(conditions)

                query += " ORDER BY trade_time DESC LIMIT :limit"
                params["limit"] = limit

                result = await conn.execute(text(query), params)
                rows = result.fetchall()

                for row in rows:
                    orders.append({
                        "order_id": getattr(row, "order_id", ""),
                        "ticker": getattr(row, "ticker", ""),
                        "side": getattr(row, "side", ""),
                        "quantity": getattr(row, "quantity", 0),
                        "price": getattr(row, "price", 0.0),
                        "notional": getattr(row, "notional", 0.0),
                        "commission": getattr(row, "commission", 0.0),
                        "trade_date": (
                            row.trade_date.isoformat()
                            if hasattr(row, "trade_date") and row.trade_date
                            else None
                        ),
                        "trade_time": (
                            row.trade_time.isoformat()
                            if hasattr(row, "trade_time") and row.trade_time
                            else None
                        ),
                        "market": getattr(row, "market", ""),
                        "strategy": getattr(row, "strategy", ""),
                        "source": "db",
                    })
        except Exception as e:
            log.warning(f"DB trade query failed (non-fatal): {e}")

        # Sort by timestamp descending
        orders.sort(
            key=lambda o: o.get("placed_at", o.get("trade_time", 0)) or 0,
            reverse=True,
        )

        # Apply limit
        paged = orders[:limit]

        return APIResponse(
            success=True,
            message=f"Returned {len(paged)} orders",
            data={
                "orders": paged,
                "count": len(paged),
                "total": len(orders),
                "limit": limit,
            },
        )

    except Exception as e:
        log.exception(f"Failed to list orders: {e}")
        raise HTTPException(status_code=500, detail=str(e))
