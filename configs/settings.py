"""configs/settings.py – Central Pydantic BaseSettings for Quant AI Trader v2.

All environment variables use the QAT_ prefix.
Provides typed access to postgres, redis, tiger broker, API, MLflow, model,
trading, and data configs — the single configuration source for the project.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Helper: parse comma‑separated or JSON-encoded list strings
# ---------------------------------------------------------------------------

def _parse_list_str(v: object) -> list[str]:
    """Accept a Python list, a JSON array string, or a comma‑separated string."""
    if isinstance(v, list):
        return [str(x).strip() for x in v]
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("["):
            try:
                return json.loads(s)
            except (json.JSONDecodeError, TypeError):
                pass
        return [x.strip() for x in s.split(",") if x.strip()]
    return []


def _parse_list_int(v: object) -> list[int]:
    """Accept a Python list of ints, a JSON array string, or comma‑separated ints."""
    if isinstance(v, list):
        return [int(x) for x in v]
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("["):
            try:
                return [int(x) for x in json.loads(s)]
            except (json.JSONDecodeError, TypeError):
                pass
        return [int(x.strip()) for x in s.split(",") if x.strip()]
    return []


# ---------------------------------------------------------------------------
# Main Settings class
# ---------------------------------------------------------------------------

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
    API_RELOAD: bool = Field(default=False, description="Uvicorn auto‑reload flag")
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

    # ── Database (SQLite by default for dev; PostgreSQL for production) ─
    POSTGRES_URL: str = Field(
        default="sqlite+aiosqlite:///data/quant_trader.db",
        description="Async SQLAlchemy database URL (SQLite dev default; use postgresql+asyncpg://... for prod)",
    )
    POSTGRES_SYNC_URL: str = Field(
        default="sqlite+aiosqlite:///data/quant_trader.db",
        description="Sync SQLAlchemy database URL (SQLite dev default; use postgresql+psycopg2://... for prod)",
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
    TIGER_PRIVATE_KEY: str = Field(default="", description="Tiger RSA private key content (PEM)")
    TIGER_PRIVATE_KEY_PATH: str = Field(
        default="./certs/tiger_private_key.pem", description="Path to Tiger RSA private key"
    )
    TIGER_CLIENT_VERSION: str = Field(default="3.0.0")
    TIGER_LICENSE: str = Field(default="")
    TIGER_PAPER_TRADING: bool = Field(default=False, description="Tiger paper trading mode")
    TIGER_CONFIG_DIR: str = Field(default="~/.tigeropen", description="Tiger SDK config directory")

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

    # ── Model: General Parameters ────────────────────────────
    MODEL_TRAIN_EPOCHS: int = Field(default=100)
    MODEL_BATCH_SIZE: int = Field(default=256)
    MODEL_LEARNING_RATE: float = Field(default=0.001)
    MODEL_EARLY_STOPPING_ROUNDS: int = Field(default=10)
    MODEL_ENSEMBLE_WEIGHTS_UPDATE_INTERVAL: int = Field(
        default=86400, description="Ensemble weight update interval in seconds"
    )

    # ── Model: Transformer Parameters ────────────────────────
    MODEL_TRANSFORMER_LOOKBACK: int = Field(default=60, description="Transformer lookback window (days)")
    MODEL_TRANSFORMER_PREDICTION_DAYS: str = Field(
        default="[1, 5, 20]", description="Prediction horizons for transformer"
    )
    MODEL_TRANSFORMER_D_MODEL_LARGE: int = Field(default=512, description="Large model embedding dim")
    MODEL_TRANSFORMER_N_HEADS_LARGE: int = Field(default=8, description="Large model attention heads")
    MODEL_TRANSFORMER_N_LAYERS_LARGE: int = Field(default=8, description="Large model encoder layers")
    MODEL_TRANSFORMER_D_FF_LARGE: int = Field(default=1024, description="Large model feed-forward dim")
    MODEL_TRANSFORMER_D_MODEL: int = Field(default=128, description="Small/legacy model embedding dim")
    MODEL_TRANSFORMER_N_HEADS: int = Field(default=8, description="Small/legacy model attention heads")
    MODEL_TRANSFORMER_N_LAYERS: int = Field(default=4, description="Small/legacy model encoder layers")
    MODEL_TRANSFORMER_DROPOUT: float = Field(default=0.1)
    MODEL_TRANSFORMER_EPOCHS: int = Field(default=80)
    MODEL_TRANSFORMER_BATCH_SIZE: int = Field(default=256)
    MODEL_TRANSFORMER_LEARNING_RATE: float = Field(default=5e-5)
    MODEL_TRANSFORMER_PATIENCE: int = Field(default=15, description="Early‑stopping patience")

    # ── Model: Training ──────────────────────────────────────
    MODEL_TRAIN_TICKERS: int = Field(default=50, description="Number of tickers to train on")
    MODEL_TRAIN_PERIOD: str = Field(default="2y", description="Training data period")
    MODEL_WALK_FORWARD_SPLITS: int = Field(default=5)
    MODEL_RETRAIN_INTERVAL_DAYS: int = Field(default=3, description="Days between retrain cycles")
    MODEL_WALK_FORWARD_WINDOW: int = Field(default=252)
    MODEL_VALIDATION_SPLIT: float = Field(default=0.2)

    # ── Model: Reinforcement Learning ────────────────────────
    MODEL_RL_LEARNING_RATE: float = Field(default=2e-4)
    MODEL_RL_N_STEPS: int = Field(default=4096)
    MODEL_RL_BATCH_SIZE: int = Field(default=256)
    MODEL_RL_GAMMA: float = Field(default=0.99)
    MODEL_RL_GAE_LAMBDA: float = Field(default=0.95)
    MODEL_RL_CLIP_RANGE: float = Field(default=0.15)
    MODEL_RL_ENT_COEF: float = Field(default=0.005)
    MODEL_RL_TOTAL_TIMESTEPS: int = Field(default=200000)
    MODEL_RL_MAX_TRADE_PERCENT: float = Field(default=0.20)

    # ── Model: Sentiment ─────────────────────────────────────
    MODEL_SENTIMENT_MODEL: str = Field(default="yiyanghkust/finbert-tone")
    MODEL_SENTIMENT_MAX_LENGTH: int = Field(default=512)

    # ── Model: Ensemble ──────────────────────────────────────
    MODEL_ENSEMBLE_WEIGHTS: str = Field(
        default='{"transformer": 0.35, "rl_agent": 0.25, "sentiment": 0.05, '
        '"technical": 0.15, "cross_stock": 0.10, "macro": 0.10}',
        description="Ensemble model weights as JSON string",
    )

    # ── Model: Macro ─────────────────────────────────────────
    MODEL_MACRO_ENABLED: bool = Field(default=True)
    MODEL_MACRO_UPDATE_INTERVAL: int = Field(default=600, description="Macro data refresh interval (s)")
    MODEL_MACRO_VIX_BEARISH: float = Field(default=30.0, description="VIX above = bearish regime")
    MODEL_MACRO_VIX_BULLISH: float = Field(default=15.0, description="VIX below = bullish regime")

    # ── Data: Stock Universe ─────────────────────────────────
    # Focus: US equities by default. Leave non-US lists empty unless expanded.
    ENABLED_MARKETS: str = Field(
        default="US",
        description="Comma-separated markets to trade/scan (e.g. US or US,HK)",
    )
    DATA_US_TICKERS: str = Field(
        default="AAPL,MSFT,GOOGL,AMZN,NVDA,META,TSLA,JPM,V,SPY,QQQ,IWM",
        description="Comma‑separated US tickers",
    )
    DATA_HK_TICKERS: str = Field(
        default="",
        description="Comma‑separated HK tickers (5‑digit numeric); empty = US-only",
    )
    DATA_SG_TICKERS: str = Field(
        default="",
        description="Comma‑separated SG tickers; empty = US-only",
    )
    DATA_AU_TICKERS: str = Field(
        default="",
        description="Comma‑separated AU tickers; empty = US-only",
    )
    DATA_NZ_TICKERS: str = Field(
        default="",
        description="Comma‑separated NZ tickers; empty = US-only",
    )

    # ── Data: General ────────────────────────────────────────
    DATA_BENCHMARK: str = Field(default="SPY", description="Benchmark ticker")
    DATA_HISTORY_DAYS: int = Field(default=730, description="Days of history to fetch")
    DATA_UPDATE_INTERVAL: int = Field(default=60, description="Data refresh interval (seconds)")
    DATA_USD_HKD_RATE: float = Field(default=7.82, description="USD→HKD peg rate")

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

    # ── Trading ──────────────────────────────────────────────
    TRADING_INITIAL_CAPITAL: float = Field(default=10000.0, description="Initial trading capital")
    TRADING_BASE_CURRENCY: str = Field(default="USD")
    TRADING_SIMULATION_MODE: bool = Field(
        default=True,
        description="Paper/sim lock — must be false AND live promotion approved for live orders",
    )

    TRADING_CURRENCY_RATES: str = Field(
        default='{"USD": 1.0, "HKD": 0.128, "SGD": 0.75, "AUD": 0.67, "NZD": 0.62}',
        description="Currency → USD conversion rates (JSON)",
    )

    TRADING_MAX_POSITION_SIZE: float = Field(default=0.50, description="Max single‑position weight")
    TRADING_MAX_PORTFOLIO_RISK: float = Field(default=0.03)
    TRADING_STOP_LOSS_PCT: float = Field(default=0.05)
    TRADING_TAKE_PROFIT_PCT: float = Field(default=0.15)
    TRADING_MAX_DRAWDOWN: float = Field(default=0.25)
    TRADING_VAR_CONFIDENCE: float = Field(default=0.95)
    TRADING_COMMISSION_RATE: float = Field(default=0.001)
    TRADING_SLIPPAGE: float = Field(default=0.0005)
    TRADING_MIN_CONFIDENCE: float = Field(default=0.15)
    TRADING_MIN_TRADE_VALUE: float = Field(default=300.0)
    TRADING_MIN_SHARES: int = Field(default=1)
    TRADING_NO_LEVERAGE: bool = Field(default=True, description="Disable leverage entirely")
    TRADING_MAX_CASH_USAGE: float = Field(default=0.95, description="Max portion of cash to deploy")
    TRADING_MAX_DAILY_TRADES: int = Field(default=0, description="0 = unlimited")
    TRADING_CYCLE_INTERVAL: int = Field(default=600, description="Auto‑trade cycle interval (s)")

    TRADING_DAILY_LOSS_LIMIT: float = Field(default=0.05, description="5% daily loss → circuit breaker")
    TRADING_CIRCUIT_BREAKER_COOLDOWN: int = Field(default=900, description="Cooldown seconds after breaker")

    # ── Training ─────────────────────────────────────────────
    TRAIN_DEVICE: str = Field(default="cpu", description="PyTorch training device (cpu/cuda)")

    # ── Docker ───────────────────────────────────────────────
    USE_DOCKER: bool = Field(default=False, description="Whether running inside Docker")

    # ── Slack Alerts ─────────────────────────────────────────
    SLACK_BOT_TOKEN: str = Field(default="")
    SLACK_ALERT_CHANNEL: str = Field(default="#quant-alerts")
    SLACK_TRADE_CHANNEL: str = Field(default="#quant-trades")

    # ── Market Calendar ──────────────────────────────────────
    MARKET_CONFIGS: str = Field(
        default=(
            '{"US": {"timezone": "US/Eastern", "open": "09:30", "close": "16:00", "currency": "USD"}, '
            '"HK": {"timezone": "Asia/Hong_Kong", "open": "09:30", "close": "16:00", "currency": "HKD"}, '
            '"SG": {"timezone": "Asia/Singapore", "open": "09:00", "close": "17:00", "currency": "SGD"}, '
            '"AU": {"timezone": "Australia/Sydney", "open": "10:00", "close": "16:00", "currency": "AUD"}, '
            '"NZ": {"timezone": "Pacific/Auckland", "open": "10:00", "close": "16:45", "currency": "NZD"}}'
        ),
        description="Market calendar configs as JSON string",
    )

    # ── Validators ───────────────────────────────────────────

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: object) -> str:
        """Normalize CORS origins to a comma-separated string."""
        if isinstance(v, list):
            return ",".join(str(x).strip() for x in v)
        return str(v) if v else ""

    # ── Properties: Path Helpers ─────────────────────────────

    @property
    def _project_root_path(self) -> Path:
        return Path(self.PROJECT_ROOT).resolve()

    @property
    def DATA_DIR(self) -> Path:
        return self._project_root_path / "data"

    @property
    def MODELS_DIR(self) -> Path:
        return self._project_root_path / "data" / "models"

    @property
    def DB_PATH(self) -> Path:
        return self.DATA_DIR / "quant_trader.db"

    @property
    def CACHE_DIR(self) -> Path:
        return self._project_root_path / "cache"

    @property
    def LOGS_DIR(self) -> Path:
        return Path(self.LOG_DIR) if Path(self.LOG_DIR).is_absolute() else self._project_root_path / self.LOG_DIR

    @property
    def TORCH_CACHE(self) -> Path:
        return self.CACHE_DIR / "torch"

    @property
    def HF_CACHE(self) -> Path:
        return self.CACHE_DIR / "huggingface"

    @property
    def YF_CACHE(self) -> Path:
        return self.CACHE_DIR / "yfinance"

    # ── Properties: CORS ─────────────────────────────────────

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

    # ── Properties: Data Ticker Helpers ──────────────────────

    @property
    def enabled_markets_list(self) -> list[str]:
        markets = [m.strip().upper() for m in _parse_list_str(self.ENABLED_MARKETS)]
        return markets or ["US"]

    @property
    def data_us_tickers_list(self) -> list[str]:
        return _parse_list_str(self.DATA_US_TICKERS)

    @property
    def data_hk_tickers_list(self) -> list[str]:
        if "HK" not in self.enabled_markets_list:
            return []
        return _parse_list_str(self.DATA_HK_TICKERS)

    @property
    def data_sg_tickers_list(self) -> list[str]:
        if "SG" not in self.enabled_markets_list:
            return []
        return _parse_list_str(self.DATA_SG_TICKERS)

    @property
    def data_au_tickers_list(self) -> list[str]:
        if "AU" not in self.enabled_markets_list:
            return []
        return _parse_list_str(self.DATA_AU_TICKERS)

    @property
    def data_nz_tickers_list(self) -> list[str]:
        if "NZ" not in self.enabled_markets_list:
            return []
        return _parse_list_str(self.DATA_NZ_TICKERS)

    @property
    def DATA_ALL_TICKERS(self) -> list[str]:
        """All tickers across all markets with proper Yahoo‑style suffixes."""
        _hk_map = {
            "00700": "0700", "09988": "9988", "03690": "3690", "09999": "9999",
            "01810": "1810", "00941": "0941", "00883": "0883", "01299": "1299",
        }
        return (
            self.data_us_tickers_list
            + [f"{_hk_map.get(t, t)}.HK" for t in self.data_hk_tickers_list]
            + self.data_sg_tickers_list
            + self.data_au_tickers_list
            + self.data_nz_tickers_list
        )

    @property
    def DATA_TICKER_INFO(self) -> list[dict[str, str]]:
        """Per‑ticker metadata dicts (symbol, name, market, currency)."""
        _hk_map = {
            "00700": "0700", "09988": "9988", "03690": "3690", "09999": "9999",
            "01810": "1810", "00941": "0941", "00883": "0883", "01299": "1299",
        }
        result: list[dict[str, str]] = []
        for t in self.data_us_tickers_list:
            result.append({"symbol": t, "name": t, "market": "US", "currency": "USD"})
        for t in self.data_hk_tickers_list:
            result.append({"symbol": f"{_hk_map.get(t, t)}.HK", "name": t, "market": "HK", "currency": "HKD"})
        for t in self.data_sg_tickers_list:
            result.append({"symbol": t, "name": t.replace(".SI", ""), "market": "SG", "currency": "SGD"})
        for t in self.data_au_tickers_list:
            result.append({"symbol": t, "name": t.replace(".AX", ""), "market": "AU", "currency": "AUD"})
        for t in self.data_nz_tickers_list:
            result.append({"symbol": t, "name": t.replace(".NZ", ""), "market": "NZ", "currency": "NZD"})
        return result

    # ── Properties: Model Helpers ────────────────────────────

    @property
    def model_transformer_prediction_days_list(self) -> list[int]:
        return _parse_list_int(self.MODEL_TRANSFORMER_PREDICTION_DAYS)

    @property
    def model_ensemble_weights_dict(self) -> dict[str, float]:
        try:
            return json.loads(self.MODEL_ENSEMBLE_WEIGHTS)
        except (json.JSONDecodeError, TypeError):
            return {
                "transformer": 0.35, "rl_agent": 0.25, "sentiment": 0.05,
                "technical": 0.15, "cross_stock": 0.10, "macro": 0.10,
            }

    @property
    def trading_currency_rates_dict(self) -> dict[str, float]:
        try:
            return json.loads(self.TRADING_CURRENCY_RATES)
        except (json.JSONDecodeError, TypeError):
            return {"USD": 1.0, "HKD": 0.128, "SGD": 0.75, "AUD": 0.67, "NZD": 0.62}

    @property
    def market_configs_dict(self) -> dict[str, dict[str, str]]:
        try:
            return json.loads(self.MARKET_CONFIGS)
        except (json.JSONDecodeError, TypeError):
            return {}

    # ── Post‑init: ensure dirs + redirect caches ─────────────

    def ensure_directories(self) -> None:
        """Create all required project directories and redirect external caches."""
        dirs = [
            self.DATA_DIR, self.MODELS_DIR, self.CACHE_DIR, self.LOGS_DIR,
            self.TORCH_CACHE, self.HF_CACHE, self.YF_CACHE,
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

        os.environ.setdefault("TORCH_HOME", str(self.TORCH_CACHE))
        os.environ.setdefault("HF_HOME", str(self.HF_CACHE))


# ── Singleton ────────────────────────────────────────────────────
settings = Settings()
settings.ensure_directories()
