"""services/factor_service/config.py – Factor service configuration.

Uses QAT_FACTOR_ environment prefix.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class FactorServiceConfig(BaseSettings):
    """Configuration for the Factor Service microservice."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="QAT_FACTOR_",
        extra="ignore",
    )

    # Service
    SERVICE_NAME: str = Field(default="factor-service", description="Service name")
    HOST: str = Field(default="0.0.0.0")
    PORT: int = Field(default=8012)

    # Factor Engine
    IC_ROLLING_WINDOW: int = Field(default=252, description="Default rolling window for IC calculation")
    CORRELATION_THRESHOLD: float = Field(default=0.70, description="Redundant factor correlation threshold")
    DECAY_MAX_LAGS: int = Field(default=20, description="Max lags for decay analysis")
    OUTLIER_WINSORIZE_PCT: float = Field(default=0.01, description="Winsorize percentile for factor outliers (each tail)")
    NEUTRALIZE_SECTORS: bool = Field(default=True, description="Sector-neutralize factors")
    MIN_OBSERVATIONS: int = Field(default=63, description="Minimum observations for factor computation")

    # Stratification
    N_QUANTILES: int = Field(default=10, description="Number of groups for stratified backtest (5 or 10)")
    STRATIFICATION_HORIZON: str = Field(default="21d", description="Forward return horizon for stratification")


factor_config = FactorServiceConfig()
