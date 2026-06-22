"""services/model_train_service/main.py – Model training FastAPI application.

Mounted at /api/v2/train.
Provides training endpoints, hyperopt, and MLflow integration.
"""

from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from loguru import logger

from services.model_train_service.api.routes import _training_runs, router as train_router
from services.model_train_service.config import train_config, _cuda_available
from shared.core.logger import setup_logger

_START_TIME: float = time.time()
_TRAINING_JOBS_PATH: Path = Path("cache") / "training_jobs.json"


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logger()
    logger.info(f"Starting {train_config.SERVICE_NAME} on port {train_config.PORT}")

    # GPU detection – honour QAT_TRAIN_DEVICE from env (set by daemon / .env)
    device = train_config.DEVICE
    logger.info(f"[INFO] Using device: {device}")

    cuda_ok = _cuda_available()
    if cuda_ok:
        import torch
        gpu_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "unknown"
        gpu_mem = torch.cuda.get_device_properties(0).total_memory // (1024 ** 2) if torch.cuda.is_available() else 0
        logger.info(f"GPU detected: {gpu_name} ({gpu_mem} MiB), device={train_config.DEVICE}")
    else:
        logger.info(f"No CUDA GPU detected, device={train_config.DEVICE}")

    # Restore _training_runs history from disk
    if _TRAINING_JOBS_PATH.exists():
        try:
            saved = json.loads(_TRAINING_JOBS_PATH.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                _training_runs.update(saved)
                logger.info(f"Restored {len(saved)} training job(s) from {_TRAINING_JOBS_PATH}")
        except Exception as e:
            logger.warning(f"Failed to restore training jobs: {e}")

    yield

    # Persist _training_runs to disk on shutdown
    try:
        _TRAINING_JOBS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _TRAINING_JOBS_PATH.write_text(json.dumps(_training_runs, indent=2), encoding="utf-8")
        logger.info(f"Saved {len(_training_runs)} training job(s) to {_TRAINING_JOBS_PATH}")
    except Exception as e:
        logger.warning(f"Failed to persist training jobs: {e}")

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
