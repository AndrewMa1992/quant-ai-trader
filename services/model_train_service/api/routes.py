"""services/model_train_service/api/routes.py – Training API endpoints.

Endpoints:
- GET /models – List registered models
- GET /gpu – GPU status (available, usage, temperature)
- POST /train/{model_type} – Start training job (with optional device param)
- GET /training/{run_id} – Check training status / results
- POST /hyperopt – Launch hyperparameter optimisation
"""

from __future__ import annotations

import time
from typing import Any, Optional

import numpy as np
import pandas as pd
import torch
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field

from services.model_train_service.api.schemas import TrainJob, TrainRequest
from services.model_train_service.config import train_config
from services.model_train_service.data_loader import create_dataset
from services.model_train_service.trainers.gbdt_trainer import GBDTTrainer
from services.model_train_service.trainers.transformer_trainer import TransformerTrainer
from services.model_train_service.mlflow_manager import MLflowManager
from configs.settings import settings
from shared.core.logger import get_logger
from shared.schema import APIResponse

router = APIRouter()
mlflow_mgr = MLflowManager()

# In-memory training run cache
_training_runs: dict[str, dict[str, Any]] = {}
_training_counter: int = 0


def _gpu_info() -> dict[str, Any]:
    """Query GPU status via nvidia-smi / torch.cuda."""
    info: dict[str, Any] = {
        "cuda_available": torch.cuda.is_available(),
        "device_count": torch.cuda.device_count() if torch.cuda.is_available() else 0,
        "device_names": [],
        "vram_total_mb": 0,
        "vram_used_mb": 0,
        "vram_free_mb": 0,
        "temperature_c": None,
        "utilization_pct": None,
    }
    if torch.cuda.is_available():
        for i in range(torch.cuda.device_count()):
            info["device_names"].append(torch.cuda.get_device_name(i))
            props = torch.cuda.get_device_properties(i)
            info["vram_total_mb"] = props.total_memory // (1024 * 1024)
            mem_alloc = torch.cuda.memory_allocated(i) // (1024 * 1024)
            mem_reserved = torch.cuda.memory_reserved(i) // (1024 * 1024)
            info["vram_used_mb"] = mem_alloc
            info["vram_reserved_mb"] = mem_reserved
            info["vram_free_mb"] = info["vram_total_mb"] - mem_reserved
    return info


def _cleanup_gpu(model: Any) -> None:
    """Move model to CPU and free GPU memory after training."""
    if model is not None and hasattr(model, "cpu"):
        try:
            model.cpu()
        except Exception:
            pass
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        logger.info("GPU memory freed after training")


class HyperoptRequest(BaseModel):
    model_type: str = Field(default="gbdt", description="gbdt / transformer / tcn / tft")
    tickers: list[str] = Field(default_factory=list)
    n_trials: int = Field(default=100)
    start_date: str | None = None
    end_date: str | None = None
    device: str = Field(
        default_factory=lambda: settings.TRAIN_DEVICE,
        description="Compute device for hyperopt: cpu / cuda. Defaults to QAT_TRAIN_DEVICE from .env",
    )


@router.get("/gpu")
async def gpu_status() -> APIResponse:
    """Check GPU availability, VRAM usage, and device info."""
    info = _gpu_info()
    return APIResponse(
        success=True,
        message=f"{info['device_count']} GPU(s) available" if info["cuda_available"] else "No GPU available",
        data=info,
    )


@router.get("/models")
async def list_models() -> APIResponse:
    """List all registered models with their versions and stages."""
    try:
        registered_models = mlflow_mgr.list_registered_models()
        return APIResponse(
            success=True,
            message=f"Found {len(registered_models)} registered models",
            data={"models": registered_models},
        )
    except Exception as e:
        logger.error(f"Failed to list models: {e}")
        return APIResponse(
            success=True,
            message="MLflow not available — returned empty",
            data={"models": []},
        )


@router.post("/train/{model_type}")
async def train_model(
    model_type: str,
    req: TrainRequest,
    background_tasks: BackgroundTasks,
) -> APIResponse:
    """Launch a model training job.

    Supported model_type: gbdt, transformer, tcn, tft, rl
    """
    global _training_counter
    log = get_logger(__name__)

    if model_type not in ("gbdt", "transformer", "tcn", "tft", "rl"):
        raise HTTPException(status_code=400, detail=f"Unsupported model type: {model_type}")

    _training_counter += 1
    run_id = f"{model_type}_{_training_counter}_{int(time.time())}"

    _training_runs[run_id] = {
        "status": "queued",
        "model_type": model_type,
        "started_at": time.time(),
        "metrics": {},
    }

    async def _run_training() -> None:
        try:
            _training_runs[run_id]["status"] = "running"

            with mlflow_mgr.start_run(run_name=run_id) as run:
                df = create_dataset(
                    req.tickers or ["AAPL", "MSFT"],
                    req.start_date or "2023-01-01",
                    req.end_date or "2024-12-31",
                )

                if df is None or len(df) < 100:
                    _training_runs[run_id]["status"] = "failed"
                    _training_runs[run_id]["error"] = "Insufficient data"
                    return

                features = df.drop(columns=["target"], errors="ignore")
                target = df["target"] if "target" in df.columns else df["close"].pct_change(21).shift(-21)

                # ── NaN sanitisation: fill inf/NaN before feeding to trainers ──
                features = features.select_dtypes(include=["number"])
                features = features.replace([np.inf, -np.inf], np.nan)

                # Standardise DL features to prevent gradient explosion
                if model_type in ("transformer", "tcn", "tft"):
                    from sklearn.preprocessing import StandardScaler
                    scaler = StandardScaler()
                    features = pd.DataFrame(
                        scaler.fit_transform(features.fillna(0.0)),
                        index=features.index,
                        columns=features.columns,
                    )
                else:
                    features = features.fillna(0.0)

                if hasattr(target, 'fillna'):
                    target = target.fillna(0.0)
                    # Clip extreme targets for DL stability
                    if model_type in ("transformer", "tcn", "tft"):
                        target = target.clip(-0.5, 0.5)

                hyperparams = req.hyperparams or {}

                # ── Dynamic device: use request's device, fallback to settings.TRAIN_DEVICE ──
                device_req = req.device if hasattr(req, 'device') and req.device else settings.TRAIN_DEVICE
                device = device_req if torch.cuda.is_available() or device_req != "cuda" else settings.TRAIN_DEVICE
                if device == "cuda" and not torch.cuda.is_available():
                    device = "cpu"
                    log.warning("CUDA requested but not available — falling back to CPU")

                gpu_info = _gpu_info()
                _training_runs[run_id]["device"] = device
                _training_runs[run_id]["gpu_before"] = {
                    "vram_used_mb": gpu_info["vram_used_mb"],
                    "vram_free_mb": gpu_info["vram_free_mb"],
                }
                log.info(f"Training {model_type} on device={device} | VRAM used={gpu_info['vram_used_mb']}MB free={gpu_info['vram_free_mb']}MB")

                if model_type == "gbdt":
                    trainer = GBDTTrainer(
                        gbdt_type=hyperparams.get("gbdt_type", "lightgbm"),
                    )
                elif model_type == "transformer":
                    trainer = TransformerTrainer(
                        d_model=hyperparams.get("d_model"),
                        n_heads=hyperparams.get("n_heads", 8),
                        device=device,
                    )
                elif model_type == "tcn":
                    from services.model_train_service.trainers.tcn_trainer import TCNTrainer
                    trainer = TCNTrainer(device=device)
                elif model_type == "tft":
                    from services.model_train_service.trainers.tft_trainer import TFTTrainer
                    trainer = TFTTrainer(device=device)
                elif model_type == "rl":
                    from services.model_train_service.trainers.rl_trainer import RLTrainer
                    trainer = RLTrainer(device=device)
                else:
                    _training_runs[run_id]["status"] = "failed"
                    return

                metrics = trainer.fit(
                    features, target,
                    epochs=hyperparams.get("epochs", train_config.EPOCHS),
                    batch_size=hyperparams.get("batch_size", train_config.BATCH_SIZE),
                )

                # Save model checkpoint to disk (on CPU to free GPU before disk I/O)
                import os
                save_dir = train_config.MODEL_SAVE_DIR
                os.makedirs(save_dir, exist_ok=True)
                if model_type == "rl":
                    ext = "zip"
                elif model_type in ("transformer", "tcn", "tft"):
                    ext = "pt"
                else:
                    ext = "joblib"
                save_path = os.path.join(save_dir, f"{model_type}_v2.{ext}")
                trainer.save(save_path)
                log.info(f"Model saved to {save_path}")

                # ── Cleanup: move model to CPU, free GPU memory ──
                _cleanup_gpu(trainer.model)

                # Report GPU after training
                gpu_after = _gpu_info()
                _training_runs[run_id]["gpu_after"] = {
                    "vram_used_mb": gpu_after["vram_used_mb"],
                    "vram_free_mb": gpu_after["vram_free_mb"],
                }

                mlflow_mgr.log_params(hyperparams)
                mlflow_mgr.log_metrics(metrics)

                # Register model
                version = mlflow_mgr.register_model(run_id, model_type)
                _training_runs[run_id]["mlflow_run_id"] = str(run.info.run_id) if hasattr(run, "info") else ""
                _training_runs[run_id]["model_version"] = version
                _training_runs[run_id]["status"] = "completed"
                _training_runs[run_id]["metrics"] = metrics

                log.info(f"Training {run_id} completed on {device}: {metrics}")

        except Exception as e:
            log.exception(f"Training {run_id} failed: {e}")
            _training_runs[run_id]["status"] = "failed"
            _training_runs[run_id]["error"] = str(e)
            # Still try to free GPU even on failure
            try:
                _cleanup_gpu(None)
            except Exception:
                pass

    background_tasks.add_task(_run_training)

    return APIResponse(
        success=True,
        message=f"Training {model_type} started",
        data={"run_id": run_id, "status": "queued"},
    )


@router.get("/training/{run_id}")
async def get_training_status(run_id: str) -> APIResponse:
    """Get the status and results of a training run."""
    run_info = _training_runs.get(run_id)
    if run_info is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    return APIResponse(
        success=True,
        message=f"Training run {run_id}",
        data=run_info,
    )


@router.post("/hyperopt")
async def hyperopt(
    req: HyperoptRequest,
    background_tasks: BackgroundTasks,
) -> APIResponse:
    """Launch hyperparameter optimisation via Optuna."""
    global _training_counter
    log = get_logger(__name__)

    _training_counter += 1
    run_id = f"hyperopt_{req.model_type}_{_training_counter}"

    _training_runs[run_id] = {
        "status": "queued",
        "model_type": req.model_type,
        "n_trials": req.n_trials,
    }

    async def _run_hyperopt() -> None:
        try:
            from services.model_train_service.hyperopt.optuna_runner import run_hyperopt

            _training_runs[run_id]["status"] = "running"

            study_result = run_hyperopt(
                model_type=req.model_type,
                tickers=req.tickers or ["AAPL"],
                n_trials=req.n_trials,
                start_date=req.start_date or "2023-01-01",
                end_date=req.end_date or "2024-12-31",
                device=req.device,
            )

            _training_runs[run_id]["status"] = "completed"
            _training_runs[run_id]["best_params"] = study_result.get("best_params", {})
            _training_runs[run_id]["best_value"] = study_result.get("best_value")

            log.info(f"Hyperopt {run_id} done: best={study_result.get('best_value')}")

        except Exception as e:
            log.exception(f"Hyperopt {run_id} failed: {e}")
            _training_runs[run_id]["status"] = "failed"
            _training_runs[run_id]["error"] = str(e)

    background_tasks.add_task(_run_hyperopt)

    return APIResponse(
        success=True,
        message=f"Hyperopt {req.model_type} started",
        data={"run_id": run_id, "n_trials": req.n_trials},
    )


@router.post("/train")
async def train_model_unified(
    req: TrainRequest,
    background_tasks: BackgroundTasks,
) -> APIResponse:
    """Unified training endpoint — model_type specified in body instead of path.

    Delegates to the existing POST /train/{model_type} logic internally.
    """
    global _training_counter
    log = get_logger(__name__)

    model_type = req.model_type
    if model_type not in ("gbdt", "transformer", "tcn", "tft", "rl"):
        raise HTTPException(status_code=400, detail=f"Unsupported model type: {model_type}")

    _training_counter += 1
    run_id = f"{model_type}_{_training_counter}_{int(time.time())}"

    _training_runs[run_id] = {
        "status": "queued",
        "model_type": model_type,
        "started_at": time.time(),
        "metrics": {},
    }

    async def _run_training() -> None:
        try:
            _training_runs[run_id]["status"] = "running"

            with mlflow_mgr.start_run(run_name=run_id) as run:
                df = create_dataset(
                    req.tickers or ["AAPL", "MSFT"],
                    req.start_date or "2023-01-01",
                    req.end_date or "2024-12-31",
                )

                if df is None or len(df) < 100:
                    _training_runs[run_id]["status"] = "failed"
                    _training_runs[run_id]["error"] = "Insufficient data"
                    return

                features = df.drop(columns=["target"], errors="ignore")
                target = df["target"] if "target" in df.columns else df["close"].pct_change(21).shift(-21)

                # ── NaN sanitisation: fill inf/NaN before feeding to trainers ──
                features = features.select_dtypes(include=["number"])
                features = features.replace([np.inf, -np.inf], np.nan)

                # Standardise DL features to prevent gradient explosion
                if model_type in ("transformer", "tcn", "tft"):
                    from sklearn.preprocessing import StandardScaler
                    scaler = StandardScaler()
                    features = pd.DataFrame(
                        scaler.fit_transform(features.fillna(0.0)),
                        index=features.index,
                        columns=features.columns,
                    )
                else:
                    features = features.fillna(0.0)

                if hasattr(target, 'fillna'):
                    target = target.fillna(0.0)
                    # Clip extreme targets for DL stability
                    if model_type in ("transformer", "tcn", "tft"):
                        target = target.clip(-0.5, 0.5)

                hyperparams = req.hyperparams or {}

                # ── Dynamic device: use request's device, fallback to settings.TRAIN_DEVICE ──
                device_req = req.device if hasattr(req, 'device') and req.device else settings.TRAIN_DEVICE
                device = device_req if torch.cuda.is_available() or device_req != "cuda" else settings.TRAIN_DEVICE
                if device == "cuda" and not torch.cuda.is_available():
                    device = "cpu"
                    log.warning("CUDA requested but not available — falling back to CPU")

                gpu_before = _gpu_info()
                _training_runs[run_id]["device"] = device
                _training_runs[run_id]["gpu_before"] = {
                    "vram_used_mb": gpu_before["vram_used_mb"],
                    "vram_free_mb": gpu_before["vram_free_mb"],
                }
                log.info(f"Training {model_type} on device={device} | VRAM used={gpu_before['vram_used_mb']}MB free={gpu_before['vram_free_mb']}MB")

                if model_type == "gbdt":
                    trainer = GBDTTrainer(
                        gbdt_type=hyperparams.get("gbdt_type", "lightgbm"),
                    )
                elif model_type == "transformer":
                    trainer = TransformerTrainer(
                        d_model=hyperparams.get("d_model"),
                        n_heads=hyperparams.get("n_heads", 8),
                        device=device,
                    )
                elif model_type == "tcn":
                    from services.model_train_service.trainers.tcn_trainer import TCNTrainer
                    trainer = TCNTrainer(device=device)
                elif model_type == "tft":
                    from services.model_train_service.trainers.tft_trainer import TFTTrainer
                    trainer = TFTTrainer(device=device)
                elif model_type == "rl":
                    from services.model_train_service.trainers.rl_trainer import RLTrainer
                    trainer = RLTrainer(device=device)
                else:
                    _training_runs[run_id]["status"] = "failed"
                    return

                metrics = trainer.fit(
                    features, target,
                    epochs=hyperparams.get("epochs", train_config.EPOCHS),
                    batch_size=hyperparams.get("batch_size", train_config.BATCH_SIZE),
                )

                # Save model checkpoint to disk
                import os as _os
                _save_dir = train_config.MODEL_SAVE_DIR
                _os.makedirs(_save_dir, exist_ok=True)
                if model_type == "rl":
                    _ext = "zip"
                elif model_type in ("transformer", "tcn", "tft"):
                    _ext = "pt"
                else:
                    _ext = "joblib"
                _save_path = _os.path.join(_save_dir, f"{model_type}_v2.{_ext}")
                trainer.save(_save_path)
                log.info(f"Model saved to {_save_path}")

                # ── GPU cleanup ──
                _cleanup_gpu(trainer.model)

                gpu_after = _gpu_info()
                _training_runs[run_id]["gpu_after"] = {
                    "vram_used_mb": gpu_after["vram_used_mb"],
                    "vram_free_mb": gpu_after["vram_free_mb"],
                }

                mlflow_mgr.log_params(hyperparams)
                mlflow_mgr.log_metrics(metrics)

                version = mlflow_mgr.register_model(run_id, model_type)
                _training_runs[run_id]["mlflow_run_id"] = str(run.info.run_id) if hasattr(run, "info") else ""
                _training_runs[run_id]["model_version"] = version
                _training_runs[run_id]["status"] = "completed"
                _training_runs[run_id]["metrics"] = metrics

                log.info(f"Training {run_id} completed on {device}: {metrics}")

        except Exception as e:
            log.exception(f"Training {run_id} failed: {e}")
            _training_runs[run_id]["status"] = "failed"
            _training_runs[run_id]["error"] = str(e)
            try:
                _cleanup_gpu(None)
            except Exception:
                pass

    background_tasks.add_task(_run_training)

    return APIResponse(
        success=True,
        message=f"Training {model_type} started",
        data={"run_id": run_id, "status": "queued"},
    )


@router.get("/train/{job_id}")
async def get_train_job(job_id: str) -> APIResponse:
    """Alias for GET /training/{run_id} — PRD semantic alignment.

    Redirects conceptually to the training run status lookup.
    """
    run_info = _training_runs.get(job_id)
    if run_info is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return APIResponse(
        success=True,
        message=f"Training job {job_id}",
        data=run_info,
    )
