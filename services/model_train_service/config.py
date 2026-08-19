"""services/model_train_service/config.py – Model training service configuration.

Uses QAT_TRAIN_ environment prefix.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _cuda_available() -> bool:
    """Check if CUDA GPU is available for training."""
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


class TrainServiceConfig(BaseSettings):
    """Configuration for the Model Training microservice."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="QAT_TRAIN_",
        extra="ignore",
    )

    SERVICE_NAME: str = Field(default="model-train-service")
    HOST: str = Field(default="0.0.0.0")
    PORT: int = Field(default=8013)

    # Training (RTX 3060 friendly defaults)
    TRAIN_WINDOW_DAYS: int = Field(default=252, description="Training window in trading days")
    VALID_WINDOW_DAYS: int = Field(default=63, description="Validation window days")
    TEST_WINDOW_DAYS: int = Field(default=63, description="Test window days")
    WALK_FORWARD_STEP_DAYS: int = Field(default=63, description="Walk-forward step size days")
    EPOCHS: int = Field(default=80)
    BATCH_SIZE: int = Field(default=128)
    LEARNING_RATE: float = Field(default=0.0005)
    EARLY_STOPPING_PATIENCE: int = Field(default=10)

    # GPU – auto-detect CUDA, fallback to CPU
    DEVICE: str = Field(
        default_factory=lambda: "cuda" if _cuda_available() else "cpu",
        description="Compute device (cpu / cuda / mps). Auto-detects CUDA; falls back to cpu.",
    )
    USE_AMP: bool = Field(default=True, description="CUDA automatic mixed precision")

    # Model Architecture defaults (RTX 3060 8-12GB friendly; was 512/8 layers)
    TRANSFORMER_D_MODEL_GPU: int = Field(default=256)
    TRANSFORMER_D_MODEL_CPU: int = Field(default=128)
    TRANSFORMER_N_HEADS: int = Field(default=8)
    TRANSFORMER_N_LAYERS: int = Field(default=6)
    TRANSFORMER_DROPOUT: float = Field(default=0.1)
    GRADIENT_CLIP_VAL: float = Field(default=0.5)

    # GBDT
    GBDT_DEFAULT: str = Field(default="lightgbm", description="Default GBDT: xgboost/lightgbm/catboost")

    # RL
    RL_DEFAULT_ALGO: str = Field(default="PPO", description="Default RL: PPO or SAC")
    RL_TIMESTEPS: int = Field(default=200000, description="RL training timesteps")

    # Hyperopt
    HYPEROPT_N_TRIALS: int = Field(default=100, description="Optuna trials per study")
    HYPEROPT_N_JOBS: int = Field(default=1, description="Parallel Optuna jobs")

    # Checkpoint / output
    MODEL_SAVE_DIR: str = Field(default="./data/models", description="Model checkpoint directory")
    MODEL_REGISTRY_STAGE: str = Field(default="staging", description="Initial MLflow stage")

    # Job management
    TRAIN_JOB_TTL: int = Field(default=604800, description="Training job TTL in seconds (7 days)")


train_config = TrainServiceConfig()
