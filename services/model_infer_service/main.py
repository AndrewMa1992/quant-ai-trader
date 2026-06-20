"""services/model_infer_service/main.py – Model inference FastAPI application.

Mounted at /api/v2/infer. Loads all production models on startup.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from services.model_infer_service.api.routes import router as infer_router
from services.model_infer_service.config import infer_config
from services.model_infer_service.inference_engine import InferenceEngine
from shared.core.logger import setup_logger

_START_TIME: float = time.time()

# Global engine instance
engine: InferenceEngine | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine
    setup_logger()
    logger.add("logs/model_infer.log", rotation="10 MB", retention="7 days")
    logger.info(f"Starting {infer_config.SERVICE_NAME} on port {infer_config.PORT}")

    engine = InferenceEngine()
    load_result = engine.load_models()
    logger.info(f"Models loaded: {load_result}")

    yield

    logger.info(f"Shutting down {infer_config.SERVICE_NAME}")


app = FastAPI(
    title="Quant AI Trader – Model Inference Service",
    version="2.0.0",
    description="Multi-model inference, ensemble blending, and signal generation",
    lifespan=lifespan,
)

app.include_router(infer_router, prefix="/api/v2/infer", tags=["Inference"])


@app.get("/health")
async def health_check() -> dict:
    uptime = time.time() - _START_TIME
    status = engine.get_status() if engine else {}
    return {
        "service": infer_config.SERVICE_NAME,
        "status": "healthy",
        "uptime_seconds": round(uptime, 2),
        "models": status,
    }
