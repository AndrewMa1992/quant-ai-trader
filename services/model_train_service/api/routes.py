"""services/model_train_service/api/routes.py – Training API endpoints.

Endpoints:
- GET /models – List registered models
- POST /train/{model_type} – Start training job
- GET /training/{run_id} – Check training status / results
- POST /hyperopt – Launch hyperparameter optimisation
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field

from services.model_train_service.config import train_config
from services.model_train_service.data_loader import create_dataset
from services.model_train_service.trainers.gbdt_trainer import GBDTTrainer
from services.model_train_service.trainers.transformer_trainer import TransformerTrainer
from services.model_train_service.mlflow_manager import MLflowManager
from shared.core.logger import get_logger
from shared.schema import APIResponse

router = APIRouter()
mlflow_mgr = MLflowManager()

# In-memory training run cache
_training_runs: dict[str, dict[str, Any]] = {}
_training_counter: int = 0


class TrainRequest(BaseModel):
    tickers: list[str] = Field(default_factory=list)
    start_date: str | None = None
    end_date: str | None = None
    hyperparams: dict[str, Any] = Field(default_factory=dict)


class HyperoptRequest(BaseModel):
    model_type: str = Field(default="gbdt", description="gbdt / transformer / tcn / tft")
    tickers: list[str] = Field(default_factory=list)
    n_trials: int = Field(default=100)
    start_date: str | None = None
    end_date: str | None = None


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
    run_id = f"{model_type}_{_training_counter}_{int(__import__('time').time())}"

    _training_runs[run_id] = {
        "status": "queued",
        "model_type": model_type,
        "started_at": __import__('time').time(),
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

                if model_type == "gbdt":
                    trainer = GBDTTrainer(
                        gbdt_type=req.hyperparams.get("gbdt_type", "lightgbm"),
                    )
                elif model_type == "transformer":
                    trainer = TransformerTrainer(
                        d_model=req.hyperparams.get("d_model", 128),
                        n_heads=req.hyperparams.get("n_heads", 8),
                    )
                elif model_type == "tcn":
                    from services.model_train_service.trainers.tcn_trainer import TCNTrainer
                    trainer = TCNTrainer()
                elif model_type == "tft":
                    from services.model_train_service.trainers.tft_trainer import TFTTrainer
                    trainer = TFTTrainer()
                elif model_type == "rl":
                    from services.model_train_service.trainers.rl_trainer import RLTrainer
                    trainer = RLTrainer()
                else:
                    _training_runs[run_id]["status"] = "failed"
                    return

                metrics = trainer.fit(features, target, valid_frac=0.2)
                mlflow_mgr.log_params(req.hyperparams)
                mlflow_mgr.log_metrics(metrics)

                # Register model
                version = mlflow_mgr.register_model(run_id, model_type)
                _training_runs[run_id]["mlflow_run_id"] = str(run.info.run_id) if hasattr(run, "info") else ""
                _training_runs[run_id]["model_version"] = version
                _training_runs[run_id]["status"] = "completed"
                _training_runs[run_id]["metrics"] = metrics

                log.info(f"Training {run_id} completed: {metrics}")

        except Exception as e:
            log.exception(f"Training {run_id} failed: {e}")
            _training_runs[run_id]["status"] = "failed"
            _training_runs[run_id]["error"] = str(e)

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
