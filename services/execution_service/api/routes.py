"""services/execution_service/api/routes.py – Execution API endpoints.

Endpoints:
- POST /optimizer/markowitz – Mean-variance optimization
- POST /optimizer/bl – Black-Litterman optimization
- POST /backtest – Run event-driven backtest
- POST /execute/order – Place a real or paper order
- GET /positions – Current positions
- GET /alerts – Recent alerts
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field

from services.execution_service.config import exec_config
from services.execution_service.optimizer.markowitz import MarkowitzOptimizer
from services.execution_service.optimizer.black_litterman import BlackLittermanOptimizer
from services.execution_service.optimizer.risk_parity import RiskParityOptimizer
from services.execution_service.backtest.event_engine import BacktestEngine
from services.execution_service.live.tiger_broker import TigerBroker
from services.execution_service.live.position_tracker import PositionTracker
from services.execution_service.live.circuit_breaker import CircuitBreaker
from services.execution_service.live.alert_manager import AlertManager
from shared.core.logger import get_logger
from shared.schema import APIResponse

router = APIRouter()

# Service instances
_position_tracker = PositionTracker()
_circuit_breaker = CircuitBreaker()
_alert_manager = AlertManager()


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


class OrderRequest(BaseModel):
    ticker: str = Field(...)
    side: str = Field(default="BUY")
    quantity: int = Field(default=100)
    order_type: str = Field(default="MKT", description="MKT / LMT")
    limit_price: float | None = None
    algo: str = Field(default="twap", description="twap / vwap / pov / direct")
    account: str = Field(default="20874631")


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


@router.post("/execute/order")
async def execute_order(req: OrderRequest) -> APIResponse:
    """Place an order (paper or live)."""
    log = get_logger(__name__)
    try:
        # Circuit breaker check
        if not _circuit_breaker.allow_order(req.ticker, req.quantity):
            raise HTTPException(status_code=403, detail="Circuit breaker active — order rejected")

        broker = TigerBroker(account=req.account)
        result = await broker.place_order(
            ticker=req.ticker,
            side=req.side,
            quantity=req.quantity,
            order_type=req.order_type,
            limit_price=req.limit_price,
            algo=req.algo,
        )

        # Update position tracker
        _position_tracker.record_order(result)

        # Check alert thresholds
        _alert_manager.check_and_alert(result)

        return APIResponse(success=True, message=f"Order placed: {req.side} {req.quantity} {req.ticker}", data=result)
    except HTTPException:
        raise
    except Exception as e:
        log.exception(f"Order failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
