"""
Pipeline Configuration — Trading Pipeline 专用配置
==================================================
替代 v1 auto_trader.py 的硬编码常量，集中管理交易管线参数。
"""
from dataclasses import dataclass, field


@dataclass
class PipelineConfig:
    """交易管线全局配置"""

    # ── 调度参数 ──────────────────────────────────────────────
    CYCLE_INTERVAL_SECONDS: int = 300          # 每轮间隔（秒），默认5分钟
    # False = 24h pipeline (US 24h + rotate HK/SG/AU/NZ when in session)
    TRADING_HOURS_ONLY: bool = False
    MAX_TICKERS_PER_CYCLE: int = 9999            # 移除限制，交由市场轮询控制

    # ── 信号阈值（Top-N 替代固定阈值） ─────────────────────
    SIGNAL_THRESHOLD: float = 0.05               # 基础 floor 阈值
    SIGNAL_THRESHOLD_MIN: float = 0.05           # 最低信号强度
    MIN_CONFIDENCE: float = 0.3                  # 置信度下限
    TOP_N_SIGNALS: int = 5                       # 每轮最多选 N 个最强信号

    # ── 全市场轮询 ────────────────────────────────────────
    MARKET_ROUND_ROBIN: bool = True              # 启用市场轮询
    # US + HK/SG/AU/NZ. Override: QAT_MARKET_ROTATION=US,HK,...
    MARKET_ROTATION: list = field(
        default_factory=lambda: ["US", "HK", "SG", "AU", "NZ"]
    )
    MAX_STOCKS_PER_MARKET: int = 200             # 单市场最大股票数

    # ── 风控参数 ──────────────────────────────────────────────
    VAR_CONFIDENCE: float = 0.95               # VaR 置信水平
    VAR_LIMIT_PCT: float = 0.02                # 日 VaR 上限（组合价值百分比）
    CVAR_LIMIT_PCT: float = 0.03               # CVaR 上限（组合价值百分比）
    BARRA_EXPOSURE_MAX_Z: float = 3.0          # Barra 因子暴露 Z-score 上限
    ENABLE_RISK_CHECKS: bool = True            # 是否启用四道风控
    ENABLE_PORTFOLIO_OPT: bool = True          # 是否启用组合优化

    # ── P0-P1 新增参数 ──────────────────────────────────────────
    # Default paper for safety; set QAT_EXECUTION_MODE=live explicitly for live trading
    EXECUTION_MODE: str = "paper"              # "paper" | "live" — 通过 QAT_EXECUTION_MODE env 覆盖
    MAX_DAILY_TRADES: int = 24                 # 五市场轮询 + 小资金日内可成交次数
    DAILY_LOSS_LIMIT: float = 0.03             # 对齐 RISK_LIMITS 日亏损熔断
    LEVERAGE_LIMIT: float = 1.001              # 杠杆上限，≥ 此值阻止买入
    V1_FALLBACK_RETRIES: int = 3               # v2 服务 HTTP 调用重试次数
    ENABLE_WS_PUSH: bool = True                # 是否启用前端 WebSocket 推送
    GIT_AUTO_SYNC: bool = False                # 是否启用 Git 自动同步（默认关闭）
    FORCE_SELL_TICKERS: list = field(default_factory=list)  # 启动时强制清仓列表

    ENABLE_ALERTS: bool = True                 # 是否启用告警
    MODEL_MAX_AGE_DAYS: int = 14             # 模型过期则降仓/HOLD
    PREFER_OPEN_MARKETS: bool = True        # 轮询时优先当前开市市场

    # ── 交易参数 ──────────────────────────────────────────────
    # Floor only — live min trade comes from shared.capital_policy
    MIN_TRADE_VALUE: float = 50.0

    # ── v2 微服务地址 ─────────────────────────────────────────
    SERVICE_BASE_URLS: dict = field(default_factory=lambda: _build_service_urls())

    # ── HTTP 客户端超时 ───────────────────────────────────────
    HTTP_TIMEOUT: float = 30.0                 # httpx 请求超时（秒）
    HTTP_RETRIES: int = 3                      # 重试次数

    def __post_init__(self) -> None:
        """从环境变量覆盖关键配置；模拟锁强制 paper。"""
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
        }


# 全局单例（方便直接 import）
pipeline_config = PipelineConfig()
