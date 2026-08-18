"""services/risk_service/api/routes.py – Risk API endpoints.

Endpoints:
- GET /barra/exposure – Barra factor exposures
- GET /barra/covariance – Factor covariance matrix
- GET /var – Value at Risk
- GET /cvar – Conditional VaR
- GET /drawdown – Drawdown analysis
- POST /stress_test – Stress test scenarios
- GET /attribution – Brinson performance attribution
- POST /check – Order-level risk check
- GET /limits – Current risk limit thresholds
"""

from __future__ import annotations

from typing import Optional

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field

from services.risk_service.config import risk_config
from services.risk_service.barra.factor_exposure import BarraExposureCalculator
from services.risk_service.barra.covariance import CovarianceEstimator
from services.risk_service.risk_measures.var import VaRCalculator
from services.risk_service.risk_measures.cvar import CVaRCalculator
from services.risk_service.risk_measures.drawdown import DrawdownAnalyzer
from services.risk_service.stress_test.historical_scenarios import historical_scenario_engine
from services.risk_service.stress_test.custom_scenarios import custom_scenario_engine
from services.risk_service.attribution.brinson import BrinsonAttribution
from services.risk_service.api.schemas import RiskCheckRequest, RiskCheckResult
from shared.core.logger import get_logger
from shared.schema import APIResponse

router = APIRouter()


class StressTestRequest(BaseModel):
    scenario: str = Field(default="covid_2020", description="Scenario name")
    tickers: list[str] = Field(default_factory=list, description="Portfolio tickers")
    weights: list[float] | None = Field(default=None, description="Portfolio weights")


@router.get("/barra/exposure")
async def get_barra_exposure(
    ticker: str = Query(..., description="Ticker symbol"),
) -> APIResponse:
    """Compute Barra factor exposures for a ticker."""
    log = get_logger(__name__)
    try:
        calc = BarraExposureCalculator()
        exposures = calc.compute_exposures(ticker)
        return APIResponse(
            success=True,
            message=f"Barra exposures for {ticker}",
            data={"ticker": ticker, "exposures": exposures},
        )
    except Exception as e:
        log.exception(f"Barra exposure failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/barra/covariance")
async def get_covariance(
    tickers: str = Query(default="", description="Comma-separated tickers"),
) -> APIResponse:
    """Compute factor covariance matrix."""
    log = get_logger(__name__)
    try:
        ticker_list = [t.strip() for t in tickers.split(",") if t.strip()][:20] or ["SPY"]
        cov_est = CovarianceEstimator(halflife=risk_config.BARRA_HALFLIFE)
        matrix = cov_est.compute(ticker_list)
        return APIResponse(
            success=True,
            message=f"Covariance matrix ({matrix.shape[0]}x{matrix.shape[1]})",
            data={
                "tickers": ticker_list,
                "shape": list(matrix.shape),
                "condition_number": round(float(np.linalg.cond(matrix)), 2),
            },
        )
    except Exception as e:
        log.exception(f"Covariance failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/var")
async def get_var(
    tickers: str = Query(default="", description="Comma-separated portfolio tickers"),
    weights: str = Query(default="", description="Comma-separated weights"),
    confidence: float = Query(default=0.95, description="Confidence level"),
    method: str = Query(default="parametric", description="parametric / historical / montecarlo"),
) -> APIResponse:
    """Compute Value at Risk for a portfolio."""
    log = get_logger(__name__)
    try:
        ticker_list = [t.strip() for t in tickers.split(",") if t.strip()] or ["SPY"]
        wt_list = [float(w) for w in weights.split(",")] if weights else [1.0 / len(ticker_list)] * len(ticker_list)

        calc = VaRCalculator(confidence=confidence)
        result = calc.compute(ticker_list, wt_list, method=method)

        return APIResponse(
            success=True,
            message=f"VaR ({confidence*100:.0f}%, {method}): {result.get('var', 'N/A')}",
            data=result,
        )
    except Exception as e:
        log.exception(f"VaR failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cvar")
async def get_cvar(
    tickers: str = Query(default="", description="Comma-separated tickers"),
    weights: str = Query(default="", description="Comma-separated weights"),
    confidence: float = Query(default=0.95),
) -> APIResponse:
    """Compute Conditional VaR (Expected Shortfall)."""
    log = get_logger(__name__)
    try:
        ticker_list = [t.strip() for t in tickers.split(",") if t.strip()] or ["SPY"]
        wt_list = [float(w) for w in weights.split(",")] if weights else [1.0 / len(ticker_list)] * len(ticker_list)

        calc = CVaRCalculator(confidence=confidence)
        result = calc.compute(ticker_list, wt_list)
        return APIResponse(
            success=True,
            message=f"CVaR ({confidence*100:.0f}%): {result.get('cvar', 'N/A')}",
            data=result,
        )
    except Exception as e:
        log.exception(f"CVaR failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/drawdown")
async def get_drawdown(
    ticker: str = Query(default="SPY", description="Ticker or portfolio"),
) -> APIResponse:
    """Analyze drawdown characteristics."""
    log = get_logger(__name__)
    try:
        analyzer = DrawdownAnalyzer()
        result = analyzer.compute(ticker)
        return APIResponse(success=True, message=f"Drawdown for {ticker}", data=result)
    except Exception as e:
        log.exception(f"Drawdown failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stress_test")
async def run_stress_test(req: StressTestRequest) -> APIResponse:
    """Run a stress test scenario."""
    log = get_logger(__name__)
    try:
        tickers = req.tickers or ["SPY"]
        weights = req.weights or [1.0 / len(tickers)] * len(tickers)

        if req.scenario in ("crisis_2008", "covid_2020", "rate_hike_2022", "vol_spike_2018", "china_crash_2015"):
            result = historical_scenario_engine.run(req.scenario, tickers, weights)
        else:
            result = custom_scenario_engine.run(req.scenario, tickers, weights)

        return APIResponse(
            success=True,
            message=f"Stress test: {req.scenario}",
            data=result,
        )
    except Exception as e:
        log.exception(f"Stress test failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/attribution")
async def get_attribution(
    tickers: str = Query(default="", description="Portfolio tickers"),
    weights: str = Query(default="", description="Portfolio weights"),
    benchmark: str = Query(default="SPY", description="Benchmark ticker"),
) -> APIResponse:
    """Run Brinson performance attribution."""
    log = get_logger(__name__)
    try:
        ticker_list = [t.strip() for t in tickers.split(",") if t.strip()] or ["AAPL", "MSFT"]
        wt_list = [float(w) for w in weights.split(",")] if weights else [1.0 / len(ticker_list)] * len(ticker_list)

        brinson = BrinsonAttribution()
        result = brinson.attribute(ticker_list, wt_list, benchmark)
        return APIResponse(success=True, message="Brinson attribution", data=result)
    except Exception as e:
        log.exception(f"Attribution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/check", response_model=RiskCheckResult)
async def risk_check_order(req: RiskCheckRequest) -> RiskCheckResult:
    """Run order-level risk pre-check.

    Delegates to the global risk_checker if initialised; otherwise
    returns a development-mode pass stub.
    """
    import services.risk_service.main as main_mod

    checker = main_mod.risk_checker
    if checker is None:
        return RiskCheckResult(
            passed=True,
            reason="Risk checker not initialized — allowing in development",
        )

    try:
        result = checker.check(
            ticker=req.ticker,
            quantity=req.quantity,
            price=req.price,
            portfolio_state=req.portfolio_state,
        )
        return RiskCheckResult(**result) if isinstance(result, dict) else result
    except Exception as e:
        return RiskCheckResult(passed=False, reason=f"Risk check error: {e}")


@router.get("/limits")
async def get_risk_limits() -> APIResponse:
    """Return current risk limit thresholds from configs.risk_limits."""
    try:
        from configs.risk_limits import RISK_LIMITS
        import dataclasses

        limits_dict = dataclasses.asdict(RISK_LIMITS)
        return APIResponse(
            success=True,
            message=f"Risk limits loaded ({len(limits_dict)} parameters)",
            data=limits_dict,
        )
    except Exception as e:
        return APIResponse(
            success=False,
            message=f"Failed to read risk limits: {e}",
            data={},
        )


# ── Circuit breaker control (frontend RiskDashboard) ─────────
_breaker_state: dict = {
    "circuit_breaker_triggered": False,
    "breaker_mode": "hard",
    "daily_pnl": 0.0,
    "daily_pnl_pct": 0.0,
    "max_drawdown": 0.0,
}


@router.get("/circuit_breaker")
async def get_circuit_breaker_status() -> dict:
    """Return portfolio circuit-breaker status for the dashboard."""
    import services.risk_service.main as main_mod

    status = dict(_breaker_state)
    checker = main_mod.risk_checker
    if checker is not None and hasattr(checker, "get_status"):
        try:
            status.update(checker.get_status())
        except Exception:
            pass
    return status


@router.post("/circuit_breaker/reset")
async def reset_circuit_breaker() -> dict:
    """Force-reset circuit breaker and recalibrate peak/NAV anchors."""
    _breaker_state["circuit_breaker_triggered"] = False
    _breaker_state["daily_pnl"] = 0.0
    _breaker_state["daily_pnl_pct"] = 0.0
    return {
        "reset": True,
        "circuit_breaker_triggered": False,
        "breaker_mode": _breaker_state["breaker_mode"],
    }


@router.post("/circuit_breaker/toggle")
async def toggle_circuit_breaker_mode(payload: dict | None = None) -> dict:
    """Toggle or set breaker mode between hard and warn."""
    payload = payload or {}
    mode = str(payload.get("mode", "")).lower()
    if mode not in ("hard", "warn"):
        mode = "warn" if _breaker_state["breaker_mode"] == "hard" else "hard"
    _breaker_state["breaker_mode"] = mode
    return {"toggled": True, "breaker_mode": mode}


# ── Institutional kill switch & live promotion ───────────────
@router.get("/kill-switch")
async def get_kill_switch_status() -> dict:
    from shared.kill_switch import get_kill_switch

    return get_kill_switch().status()


@router.post("/kill-switch/engage")
async def engage_kill_switch(payload: dict | None = None) -> dict:
    from shared.kill_switch import get_kill_switch

    payload = payload or {}
    reason = str(payload.get("reason") or "manual engage")
    engaged_by = str(payload.get("engaged_by") or "api")
    return get_kill_switch().engage(reason, engaged_by=engaged_by)


@router.post("/kill-switch/reset")
async def reset_kill_switch(payload: dict | None = None) -> dict:
    from shared.kill_switch import get_kill_switch

    payload = payload or {}
    reset_by = str(payload.get("reset_by") or "api")
    _breaker_state["circuit_breaker_triggered"] = False
    return get_kill_switch().reset(reset_by=reset_by)


@router.get("/live-promotion")
async def get_live_promotion_status() -> dict:
    from shared.live_promotion import status

    return status()


@router.post("/live-promotion/approve")
async def approve_live_promotion(payload: dict | None = None) -> dict:
    from shared.live_promotion import approve_live

    payload = payload or {}
    operator = str(payload.get("operator") or "api")
    checklist = dict(payload.get("checklist") or {})
    try:
        return approve_live(operator, checklist)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/live-promotion/revoke")
async def revoke_live_promotion(payload: dict | None = None) -> dict:
    from shared.live_promotion import revoke_live

    payload = payload or {}
    return revoke_live(
        str(payload.get("operator") or "api"),
        str(payload.get("reason") or ""),
    )
