"""services/model_infer_service/config.py – Model inference service configuration.

Uses QAT_INFER_ environment prefix.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class InferServiceConfig(BaseSettings):
    """Configuration for the Model Inference microservice."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="QAT_INFER_",
        extra="ignore",
    )

    SERVICE_NAME: str = Field(default="model-infer-service")
    HOST: str = Field(default="0.0.0.0")
    PORT: int = Field(default=8014)
    DEVICE: str = Field(default="cpu")

    # Ensemble
    BAYESIAN_WINDOW_DAYS: int = Field(default=60, description="Rolling window for Bayesian weight computation")
    ENSEMBLE_MODE: str = Field(default="weighted_average", description="weighted_average / voting / stacking")
    MIN_CONFIDENCE: float = Field(default=0.3, description="Minimum confidence to include model in ensemble")
    CONFIDENCE_PENALTY: float = Field(default=0.1, description="Penalty per extra model in ensemble")

    # Model cache
    MODEL_CACHE_TTL_SECONDS: int = Field(default=3600, description="Model metadata cache TTL")
    MODEL_LOAD_TIMEOUT: int = Field(default=30, description="Model load timeout seconds")

    # Signal
    SIGNAL_SCALE: float = Field(default=1.0, description="Signal scaling factor")
    SIGNAL_CLIP: float = Field(default=1.5, description="Max abs signal value before clipping")


infer_config = InferServiceConfig()
