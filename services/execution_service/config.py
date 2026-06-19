"""services/execution_service/config.py – Execution service configuration.

Uses QAT_EXEC_ prefix.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExecutionServiceConfig(BaseSettings):
    """Configuration for the Execution microservice."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8",
        env_prefix="QAT_EXEC_", extra="ignore",
    )

    SERVICE_NAME: str = Field(default="execution-service")
    HOST: str = Field(default="0.0.0.0")
    PORT: int = Field(default=8016)

    # Portfolio
    INITIAL_CAPITAL: float = Field(default=100_000_000.0)
    MAX_POSITIONS: int = Field(default=50, description="Maximum number of concurrent positions")

    # Backtest
    BACKTEST_COMMISSION_BPS: float = Field(default=5.0)
    BACKTEST_SLIPPAGE_BPS: float = Field(default=2.0)
    BACKTEST_START_DATE: str = Field(default="2020-01-01")

    # Execution algorithms
    TWAP_DEFAULT_INTERVALS: int = Field(default=10, description="Default TWAP slice count")
    TWAP_INTERVAL_SECONDS: int = Field(default=300, description="Seconds between slices")
    VWAP_NUM_BUCKETS: int = Field(default=26, description="VWAP volume profile buckets")
    POV_DEFAULT_PARTICIPATION: float = Field(default=0.20, description="POV default participation rate")

    # Circuit breakers
    CB_DAILY_LOSS_LIMIT_PCT: float = Field(default=0.05, description="Daily loss limit (5%)")
    CB_SINGLE_ORDER_LIMIT_PCT: float = Field(default=0.02, description="Single order max loss (2%)")
    CB_COOLING_MINUTES: int = Field(default=30, description="Cool-down after 3 consecutive losses")
    CB_CONSECUTIVE_LOSS_LIMIT: int = Field(default=3)

    # Live trading
    LIVE_TRADING_REQUIRE_CONFIRM: bool = Field(default=True)
    TIGER_ACCOUNT: str = Field(default="20874631")

    # Order management
    ORDER_STATUS_TTL: int = Field(default=86400, description="Order status TTL in seconds (24 hours)")


exec_config = ExecutionServiceConfig()
