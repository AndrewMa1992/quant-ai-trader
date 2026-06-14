"""services/model_train_service/main.py – Model training FastAPI application.

Mounted at /api/v2/train.
Provides training endpoints, hyperopt, and MLflow integration.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from services.model_train_service.api.routes import router as train_router
from services.model_train_service.config import train_config
from shared.core.logger import setup_logger

_START_TIME: float = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logger()
    logger.info(f"Starting {train_config.SERVICE_NAME} on port {train_config.PORT}")
    logger.info(f"Device: {train_config.DEVICE}")
    yield
    logger.info(f"Shutting down {train_config.SERVICE_NAME}")


app = FastAPI(
    title="Quant AI Trader – Model Training Service",
    version="2.0.0",
    description="Model training, hyperparameter optimisation, and MLflow tracking",
    lifespan=lifespan,
)

app.include_router(train_router, prefix="/api/v2/train", tags=["Training"])


@app.get("/health")
async def health_check() -> dict:
    uptime = time.time() - _START_TIME
    return {
        "service": train_config.SERVICE_NAME,
        "status": "healthy",
        "uptime_seconds": round(uptime, 2),
        "device": train_config.DEVICE,
    }
