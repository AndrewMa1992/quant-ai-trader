"""services/risk_service/api/routes.py – Risk API endpoints.

Endpoints:
- GET /barra/exposure – Barra factor exposures
- GET /barra/covariance – Factor covariance matrix
- GET /var – Value at Risk
- GET /cvar – Conditional VaR
- GET /drawdown – Drawdown analysis
- POST /stress_test – Stress test scenarios
- GET /attribution – Brinson performance attribution
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
