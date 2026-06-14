"""services/data_service/main.py – Data microservice FastAPI application.

Mounted at /api/v2/data by the API Gateway. Provides:
- Historical OHLCV bars (daily & minute)
- Ticker info lookup
- Market universe management
- Data ingestion triggers
- Real-time streaming via WebSocket
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from services.data_service.api.routes import router as data_router
from services.data_service.config import data_config
from shared.core.logger import setup_logger
from shared.redis_client import close_redis, get_redis

_START_TIME: float = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage service lifecycle."""
    setup_logger()
    logger.info(f"Starting {data_config.SERVICE_NAME} on port {data_config.PORT}")

    try:
        await get_redis()
        logger.info("Redis connected")
    except Exception as e:
        logger.warning(f"Redis connection failed (non-fatal): {e}")

    yield

    logger.info(f"Shutting down {data_config.SERVICE_NAME}")
    await close_redis()


app = FastAPI(
    title="Quant AI Trader – Data Service",
    version="2.0.0",
    description="Market data ingestion, storage, and retrieval",
    lifespan=lifespan,
)

app.include_router(data_router, prefix="/api/v2/data", tags=["Data"])


@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint."""
    uptime = time.time() - _START_TIME
    return {
        "service": data_config.SERVICE_NAME,
        "status": "healthy",
        "uptime_seconds": round(uptime, 2),
    }
