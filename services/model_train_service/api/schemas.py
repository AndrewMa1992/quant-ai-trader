"""services/model_train_service/api/schemas.py – Pydantic request/response models for training API."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator

from configs.settings import settings

_ALLOWED_MODELS = {"gbdt", "transformer", "tcn", "tft", "rl", "rl_agent"}


class TrainRequest(BaseModel):
    """Unified training request body."""

    model_type: str = Field(
        default="gbdt",
        description="Model type: gbdt | transformer | tcn | tft | rl",
        examples=["gbdt", "transformer", "tcn", "tft", "rl"],
    )
    tickers: list[str] = Field(
        default_factory=lambda: ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA"],
        description="List of ticker symbols for training",
        min_length=1,
    )
    start_date: str = Field(default="2023-01-01", description="Training start date (YYYY-MM-DD)")
    end_date: str = Field(default="2024-12-31", description="Training end date (YYYY-MM-DD)")
    device: str = Field(
        default_factory=lambda: settings.TRAIN_DEVICE,
        description="Compute device: cpu / cuda / mps. Defaults to QAT_TRAIN_DEVICE.",
        examples=["cpu", "cuda"],
    )
    hyperparams: Optional[dict] = Field(
        default=None, description="Optional hyperparameter overrides"
    )

    @field_validator("model_type")
    @classmethod
    def normalize_model_type(cls, v: str) -> str:
        name = (v or "gbdt").lower().strip()
        if name == "rl_agent":
            name = "rl"
        if name not in _ALLOWED_MODELS - {"rl_agent"}:
            raise ValueError(f"Unsupported model_type: {v}")
        return name


class TrainJob(BaseModel):
    """Training job status response model."""

    job_id: str = Field(..., description="Unique job identifier (UUID)")
    model_type: str = Field(..., description="Model type: gbdt | transformer | tcn | tft | rl")
    status: str = Field(
        ..., description="Job status: queued | running | completed | failed"
    )
    metrics: Optional[dict] = Field(
        default=None, description="Training metrics (loss, sharpe, etc.)"
    )
    error: Optional[str] = Field(default=None, description="Error message if failed")
    mlflow_run_id: Optional[str] = Field(
        default=None, description="MLflow run ID for tracking"
    )
    model_version: Optional[int] = Field(
        default=None, description="Registered model version number"
    )
    created_at: float = Field(..., description="Job creation timestamp (Unix epoch)")
    completed_at: Optional[float] = Field(
        default=None, description="Job completion timestamp (Unix epoch)"
    )
