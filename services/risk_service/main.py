"""services/risk_service/main.py – Risk microservice FastAPI application.

Mounted at /api/v2/risk. Provides risk analytics, stress testing,
and order-level risk checks.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from services.risk_service.api.routes import router as risk_router
from services.risk_service.config import risk_config
from shared.core.logger import setup_logger

_START_TIME: float = time.time()

# Global risk checker instance — set during lifespan
risk_checker = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global risk_checker
    setup_logger()
    logger.info(f"Starting {risk_config.SERVICE_NAME} on port {risk_config.PORT}")

    # Attempt to initialise RiskChecker (CircuitBreaker + RiskLimits)
    try:
        from services.risk_service.risk_checker import RiskChecker
        risk_checker = RiskChecker()
        logger.info("RiskChecker initialised successfully")
    except Exception as e:
        risk_checker = None
        logger.warning(f"RiskChecker could not be initialised (development mode): {e}")

    yield

    logger.info(f"Shutting down {risk_config.SERVICE_NAME}")


app = FastAPI(
    title="Quant AI Trader – Risk Service",
    version="2.0.0",
    description="Barra risk model, VaR/CVaR, stress testing, Brinson attribution, and pre-trade checks",
    lifespan=lifespan,
)

app.include_router(risk_router, prefix="/api/v2/risk", tags=["Risk"])


@app.get("/health")
async def health_check() -> dict:
    return {
        "service": risk_config.SERVICE_NAME,
        "status": "healthy",
        "uptime_seconds": round(time.time() - _START_TIME, 2),
    }
