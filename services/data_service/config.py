"""services/data_service/config.py – Data service configuration.

Uses QAT_DATA_ environment prefix for data-service-specific settings.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DataServiceConfig(BaseSettings):
    """Configuration for the Data Service microservice."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="QAT_DATA_",
        extra="ignore",
    )

    # Service
    SERVICE_NAME: str = Field(default="data-service", description="Service name")
    HOST: str = Field(default="0.0.0.0", description="Service listen host")
    PORT: int = Field(default=8011, description="Service listen port")
    DEBUG: bool = Field(default=False, description="Debug mode")

    # Storage
    DATA_DIR: str = Field(default="./cache/market_data", description="Root directory for market data files")
    PARQUET_COMPRESSION: str = Field(default="zstd", description="Parquet compression codec")

    # Ingestion
    YFINANCE_RATE_LIMIT_SECONDS: float = Field(default=2.0, description="Minimum interval between yfinance requests")
    YFINANCE_MAX_RETRIES: int = Field(default=3, description="Max retries for yfinance calls")
    YFINANCE_RETRY_BACKOFF: float = Field(default=2.0, description="Exponential backoff multiplier")
    TIGER_RATE_LIMIT_SECONDS: float = Field(default=1.0, description="Rate limit for Tiger API calls")
    BACKFILL_YEARS: int = Field(default=5, description="Years of historical data to backfill")

    # Real-time
    WS_RECONNECT_DELAY: float = Field(default=5.0, description="WebSocket reconnect delay in seconds")
    STREAM_MAX_LEN: int = Field(default=100000, description="Max Redis Stream length")

    # Quality checks
    ZSCORE_OUTLIER_THRESHOLD: float = Field(default=4.0, description="Z-score threshold for outlier detection")
    MAX_MISSING_PCT: float = Field(default=0.15, description="Max allowed missing value percentage")
    MIN_BAR_COUNT: int = Field(default=200, description="Minimum bars required per ticker")


# Singleton
data_config = DataServiceConfig()
