"""services/model_train_service/api/schemas.py – Pydantic request/response models for training API."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class TrainRequest(BaseModel):
    """Unified training request body — no path parameter needed."""

    model_type: str = Field(
        ...,
        description="Model type: transformer | rl_agent",
        examples=["transformer", "rl_agent"],
    )
    tickers: list[str] = Field(..., description="List of ticker symbols for training", min_length=1)
    start_date: str = Field(..., description="Training start date (YYYY-MM-DD)")
    end_date: str = Field(..., description="Training end date (YYYY-MM-DD)")
    hyperparams: Optional[dict] = Field(
        default=None, description="Optional hyperparameter overrides"
    )


class TrainJob(BaseModel):
    """Training job status response model."""

    job_id: str = Field(..., description="Unique job identifier (UUID)")
    model_type: str = Field(..., description="Model type: transformer | rl_agent")
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
