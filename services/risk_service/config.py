"""services/risk_service/config.py – Risk service configuration.

Uses QAT_RISK_ environment prefix.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RiskServiceConfig(BaseSettings):
    """Configuration for the Risk microservice."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8",
        env_prefix="QAT_RISK_", extra="ignore",
    )

    SERVICE_NAME: str = Field(default="risk-service")
    HOST: str = Field(default="0.0.0.0")
    PORT: int = Field(default=8015)

    # Barra
    BARRA_HALFLIFE: int = Field(default=60, description="EWMA half-life days for covariance")
    BARRA_EIGENVALUE_FLOOR: float = Field(default=1e-8, description="Minimum eigenvalue for covariance")
    BARRA_N_FACTORS: int = Field(default=9, description="Number of Barra style factors")

    # VaR
    VAR_CONFIDENCE: float = Field(default=0.95, description="Default VaR confidence level")
    VAR_ROLLING_WINDOW: int = Field(default=252, description="Rolling window for historical VaR")
    VAR_MONTE_CARLO_PATHS: int = Field(default=10000, description="MC simulation paths")
    VAR_MONTE_CARLO_STEPS: int = Field(default=252, description="MC steps (trading days)")

    # Stress
    STRESS_SHOCK_LEVELS: list[float] = Field(default=[-0.10, -0.20, 0.10, 0.20])

    # Attribution
    ATTRIBUTION_BENCHMARK: str = Field(default="SPY", description="Default benchmark for attribution")


risk_config = RiskServiceConfig()
