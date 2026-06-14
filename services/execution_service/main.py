"""services/execution_service/main.py – Execution microservice FastAPI application.

Mounted at /api/v2/execution. Provides portfolio optimization,
backtesting, order execution, and position management.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from services.execution_service.api.routes import router as exec_router
from services.execution_service.config import exec_config
from shared.core.logger import setup_logger

_START_TIME: float = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logger()
    logger.info(f"Starting {exec_config.SERVICE_NAME} on port {exec_config.PORT}")
    yield
    logger.info(f"Shutting down {exec_config.SERVICE_NAME}")


app = FastAPI(
    title="Quant AI Trader – Execution Service",
    version="2.0.0",
    description="Portfolio optimization, event-driven backtest, order execution",
    lifespan=lifespan,
)

app.include_router(exec_router, prefix="/api/v2/execution", tags=["Execution"])


@app.get("/health")
async def health_check() -> dict:
    return {
        "service": exec_config.SERVICE_NAME,
        "status": "healthy",
        "uptime_seconds": round(time.time() - _START_TIME, 2),
    }
