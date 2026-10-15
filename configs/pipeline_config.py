"""
Pipeline Configuration — Trading Pipeline dedicated config
==========================================================
Replaces hardcoded constants from v1 auto_trader.py with centralized
pipeline parameters.
"""
from dataclasses import dataclass, field


@dataclass
class PipelineConfig:
    """Global trading-pipeline configuration."""

    # ── Scheduling ────────────────────────────────────────────────
    CYCLE_INTERVAL_SECONDS: int = 300          # Seconds between cycles; default 5 min
    # False = 24h pipeline (US 24h + rotate HK/SG/AU/NZ when in session)
    TRADING_HOURS_ONLY: bool = False
    MAX_TICKERS_PER_CYCLE: int = 9999            # Cap removed; market round-robin controls size

    # ── Signal thresholds (Top-N replaces a fixed cutoff) ─────────
    SIGNAL_THRESHOLD: float = 0.05               # Base floor threshold
    SIGNAL_THRESHOLD_MIN: float = 0.05           # Minimum signal strength
    MIN_CONFIDENCE: float = 0.3                  # Confidence floor
    TOP_N_SIGNALS: int = 5                       # Max N strongest signals per cycle

    # ── Cross-market round-robin ──────────────────────────────────
    MARKET_ROUND_ROBIN: bool = True              # Enable market rotation
    # US + HK/SG/AU/NZ. Override: QAT_MARKET_ROTATION=US,HK,...
    MARKET_ROTATION: list = field(
        default_factory=lambda: ["US", "HK", "SG", "AU", "NZ"]
    )
    MAX_STOCKS_PER_MARKET: int = 200             # Max stocks per market

    # ── Risk parameters ───────────────────────────────────────────
    VAR_CONFIDENCE: float = 0.95               # VaR confidence level
    VAR_LIMIT_PCT: float = 0.02                # Daily VaR cap (fraction of portfolio value)
    CVAR_LIMIT_PCT: float = 0.03               # CVaR cap (fraction of portfolio value)
    BARRA_EXPOSURE_MAX_Z: float = 3.0          # Barra factor-exposure Z-score cap
    ENABLE_RISK_CHECKS: bool = True            # Enable four-layer risk checks
    ENABLE_PORTFOLIO_OPT: bool = True          # Enable portfolio optimization

    # ── P0-P1 additions ───────────────────────────────────────────
    # Default paper for safety; set QAT_EXECUTION_MODE=live explicitly for live trading
    EXECUTION_MODE: str = "paper"              # "paper" | "live" — override via QAT_EXECUTION_MODE
    MAX_DAILY_TRADES: int = 24                 # Five-market rotation + small-capital intra-day fill budget
    DAILY_LOSS_LIMIT: float = 0.03             # Align with RISK_LIMITS daily-loss circuit breaker
    LEVERAGE_LIMIT: float = 1.001              # Leverage cap; ≥ this value blocks buys
    V1_FALLBACK_RETRIES: int = 3               # HTTP retry count for v2 service calls
    ENABLE_WS_PUSH: bool = True                # Enable frontend WebSocket push
    GIT_AUTO_SYNC: bool = False                # Enable Git auto-sync (off by default)
    FORCE_SELL_TICKERS: list = field(default_factory=list)  # Tickers to force-liquidate on startup

    ENABLE_ALERTS: bool = True                 # Enable alerts
    MODEL_MAX_AGE_DAYS: int = 14             # Stale models → reduce size / HOLD
    PREFER_OPEN_MARKETS: bool = True        # Prefer currently open markets during rotation

    # ── Trade parameters ──────────────────────────────────────────
    # Floor only — live min trade comes from shared.capital_policy
    MIN_TRADE_VALUE: float = 50.0

    # ── v2 microservice URLs ──────────────────────────────────────
    SERVICE_BASE_URLS: dict = field(default_factory=lambda: _build_service_urls())

    # ── HTTP client timeouts ──────────────────────────────────────
    HTTP_TIMEOUT: float = 30.0                 # httpx request timeout (seconds)
    HTTP_RETRIES: int = 3                      # Retry count

    def __post_init__(self) -> None:
        """Override key settings from env; simulation lock forces paper."""
        import os

        self.EXECUTION_MODE = os.getenv("QAT_EXECUTION_MODE", self.EXECUTION_MODE)
        rot = os.getenv("QAT_MARKET_ROTATION", "").strip()
        if rot:
            self.MARKET_ROTATION = [m.strip().upper() for m in rot.split(",") if m.strip()]
            if not self.MARKET_ROTATION:
                self.MARKET_ROTATION = ["US", "HK", "SG", "AU", "NZ"]
        hours_only = os.getenv("QAT_TRADING_HOURS_ONLY", "").strip().lower()
        if hours_only in ("1", "true", "yes", "on"):
            self.TRADING_HOURS_ONLY = True
        elif hours_only in ("0", "false", "no", "off"):
            self.TRADING_HOURS_ONLY = False
        try:
            from shared.execution_mode import get_execution_mode

            self.EXECUTION_MODE = get_execution_mode()
        except Exception:
            sim = os.getenv("QAT_TRADING_SIMULATION_MODE", "true").strip().lower()
            if sim in ("1", "true", "yes", "on", ""):
                self.EXECUTION_MODE = "paper"


def _build_service_urls() -> dict:
    """Dynamically read service ports from central settings / discovery."""
    try:
        from shared.service_discovery import service_base_url

        return {
            "data": service_base_url("data"),
            "factor": service_base_url("factor"),
            "model_train": service_base_url("model_train"),
            "model_infer": service_base_url("model_infer"),
            "risk": service_base_url("risk"),
            "execution": service_base_url("execution"),
            "api": service_base_url("api"),
        }
    except Exception:
        from configs.settings import settings

        return {
            "data": f"http://localhost:{settings.DATA_PORT}",
            "factor": f"http://localhost:{settings.FACTOR_PORT}",
            "model_train": f"http://localhost:{settings.MODEL_TRAIN_PORT}",
            "model_infer": f"http://localhost:{settings.MODEL_INFER_PORT}",
            "risk": f"http://localhost:{settings.RISK_PORT}",
            "execution": f"http://localhost:{settings.EXEC_PORT}",
            "api": f"http://localhost:{settings.API_PORT}",
        }


# Global singleton (convenient to import directly)
pipeline_config = PipelineConfig()
