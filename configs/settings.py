"""configs/settings.py – Central Pydantic BaseSettings for Quant AI Trader v2.

All environment variables use the QAT_ prefix.
Provides typed access to postgres, redis, tiger broker, API, and MLflow configs.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Root settings loaded from .env file with QAT_ prefix."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="QAT_",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Application ──────────────────────────────────────────
    PROJECT_ROOT: str = Field(default=".", description="Project root directory")
    APP_NAME: str = Field(default="quant-ai-trader", description="Application name")
    APP_VERSION: str = Field(default="2.0.0", description="Application version")
    ENV: str = Field(default="development", description="Runtime environment")
    DEBUG: bool = Field(default=True, description="Debug mode toggle")
    LOG_LEVEL: str = Field(default="INFO", description="Loguru log level")
    LOG_DIR: str = Field(default="./logs", description="Log file output directory")

    # ── API Gateway ──────────────────────────────────────────
    API_PORT: int = Field(default=8001, description="API gateway listen port")
    API_HOST: str = Field(default="0.0.0.0", description="API gateway listen host")
    API_KEY: str = Field(
        default="dev-api-key-change-in-production", description="API key for authentication"
    )
    CORS_ORIGINS: str = Field(
        default="http://localhost:5173,http://localhost:3000",
        description="CORS allowed origins (comma-separated string)",
    )

    # ── Microservice Ports ───────────────────────────────────
    DATA_PORT: int = Field(default=8011, description="Data service listen port")
    FACTOR_PORT: int = Field(default=8012, description="Factor service listen port")
    MODEL_TRAIN_PORT: int = Field(default=8013, description="Model training service listen port")
    MODEL_INFER_PORT: int = Field(default=8014, description="Model inference service listen port")
    RISK_PORT: int = Field(default=8015, description="Risk service listen port")
    EXEC_PORT: int = Field(default=8016, description="Execution service listen port")

    # ── PostgreSQL ───────────────────────────────────────────
    POSTGRES_URL: str = Field(
        default="postgresql+asyncpg://qat:qat_secret@localhost:5432/quant_trader",
        description="Async SQLAlchemy database URL",
    )
    POSTGRES_SYNC_URL: str = Field(
        default="postgresql+psycopg2://qat:qat_secret@localhost:5432/quant_trader",
        description="Sync SQLAlchemy database URL (Alembic)",
    )
    POSTGRES_USER: str = Field(default="qat")
    POSTGRES_PASSWORD: str = Field(default="qat_secret")
    POSTGRES_DB: str = Field(default="quant_trader")
    POSTGRES_HOST: str = Field(default="localhost")
    POSTGRES_PORT: int = Field(default=5432)
    POSTGRES_POOL_SIZE: int = Field(default=20, description="asyncpg connection pool size")
    POSTGRES_MAX_OVERFLOW: int = Field(default=10, description="Max overflow connections")
    POSTGRES_POOL_TIMEOUT: int = Field(default=30, description="Pool timeout seconds")
    POSTGRES_ECHO_SQL: bool = Field(default=False, description="Log all SQL statements")

    # ── Redis ────────────────────────────────────────────────
    REDIS_URL: str = Field(
        default="redis://:redis_secret@localhost:6379/0", description="Redis connection URL"
    )
    REDIS_PASSWORD: str = Field(default="redis_secret")
    REDIS_HOST: str = Field(default="localhost")
    REDIS_PORT: int = Field(default=6379)
    REDIS_DB: int = Field(default=0)
    REDIS_MAX_CONNECTIONS: int = Field(default=50)

    # ── Tiger Broker API ─────────────────────────────────────
    TIGER_ID: str = Field(default="", description="Tiger broker ID")
    TIGER_ACCOUNT: str = Field(default="", description="Tiger account number")
    TIGER_PRIVATE_KEY_PATH: str = Field(
        default="./certs/tiger_private_key.pem", description="Path to Tiger RSA private key"
    )
    TIGER_CLIENT_VERSION: str = Field(default="3.0.0")
    TIGER_LICENSE: str = Field(default="")

    # ── External Data APIs ───────────────────────────────────
    ALPHA_VANTAGE_KEY: str = Field(default="")
    POLYGON_KEY: str = Field(default="")
    WIND_API_KEY: str = Field(default="")

    # ── MLflow ───────────────────────────────────────────────
    MLFLOW_TRACKING_URI: str = Field(
        default="http://localhost:5000", description="MLflow tracking server URI"
    )
    MLFLOW_PORT: int = Field(default=5000)
    MLFLOW_ARTIFACT_ROOT: str = Field(default="./mlruns")

    # ── Model Parameters ─────────────────────────────────────
    MODEL_TRAIN_EPOCHS: int = Field(default=100)
    MODEL_BATCH_SIZE: int = Field(default=256)
    MODEL_LEARNING_RATE: float = Field(default=0.001)
    MODEL_EARLY_STOPPING_ROUNDS: int = Field(default=10)
    MODEL_ENSEMBLE_WEIGHTS_UPDATE_INTERVAL: int = Field(
        default=86400, description="Ensemble weight update interval in seconds"
    )

    # ── Backtest ─────────────────────────────────────────────
    BACKTEST_START_DATE: str = Field(default="2020-01-01")
    BACKTEST_END_DATE: str = Field(default="2024-12-31")
    BACKTEST_INITIAL_CAPITAL: float = Field(default=100_000_000.0)
    BACKTEST_COMMISSION_BPS: float = Field(default=5.0, description="Commission in basis points")
    BACKTEST_SLIPPAGE_BPS: float = Field(default=2.0, description="Slippage in basis points")

    # ── Execution ────────────────────────────────────────────
    EXECUTION_MODE: str = Field(
        default="paper", description="Execution mode: paper or live"
    )
    EXECUTION_MAX_SLIPPAGE_BPS: float = Field(default=10.0)
    EXECUTION_ORDER_TIMEOUT_SECONDS: int = Field(default=30)
    EXECUTION_RETRY_ATTEMPTS: int = Field(default=3)

    # ── Training ─────────────────────────────────────────────
    TRAIN_DEVICE: str = Field(default="cpu", description="PyTorch training device (cpu/cuda)")

    # ── Docker ───────────────────────────────────────────────
    USE_DOCKER: bool = Field(default=False, description="Whether running inside Docker")

    # ── Slack Alerts ─────────────────────────────────────────
    SLACK_BOT_TOKEN: str = Field(default="")
    SLACK_ALERT_CHANNEL: str = Field(default="#quant-alerts")
    SLACK_TRADE_CHANNEL: str = Field(default="#quant-trades")

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: object) -> str:
        """Normalize CORS origins to a comma-separated string."""
        if isinstance(v, list):
            return ",".join(str(x).strip() for x in v)
        return str(v) if v else ""

    @property
    def cors_origin_list(self) -> list[str]:
        """Return CORS origins as a list for FastAPI middleware."""
        if not self.CORS_ORIGINS:
            return ["*"]
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.ENV.lower() == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development mode."""
        return self.ENV.lower() in ("development", "dev")


# Singleton settings instance
settings = Settings()
