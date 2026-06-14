"""services/factor_service/main.py – Factor microservice FastAPI application.

Provides factor computation, evaluation, and analysis endpoints.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from services.factor_service.api.routes import router as factor_router
from services.factor_service.config import factor_config
from shared.core.logger import setup_logger

_START_TIME: float = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logger()
    logger.info(f"Starting {factor_config.SERVICE_NAME} on port {factor_config.PORT}")

    # Pre-load factor engine
    from services.factor_service.engine.factor_engine import FactorEngine
    global _engine
    _engine = FactorEngine()
    _engine.register_all()
    logger.info(f"Factor engine initialized with {len(_engine.factors)} factors")

    yield
    logger.info(f"Shutting down {factor_config.SERVICE_NAME}")


app = FastAPI(
    title="Quant AI Trader – Factor Service",
    version="2.0.0",
    description="Factor computation, evaluation, and analysis",
    lifespan=lifespan,
)

app.include_router(factor_router, prefix="/api/v2/factors", tags=["Factors"])

# Module-level engine reference
_engine = None


@app.get("/health")
async def health_check() -> dict:
    uptime = time.time() - _START_TIME
    return {
        "service": factor_config.SERVICE_NAME,
        "status": "healthy",
        "uptime_seconds": round(uptime, 2),
        "factors_loaded": len(_engine.factors) if _engine else 0,
    }
