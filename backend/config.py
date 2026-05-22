"""
Quant AI Trader - 全局配置
顶级量化基金级别的配置管理
"""
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List

# 加载 .env 文件（优先，不提交到 Git）
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent.parent / ".env"
    load_dotenv(_env_path)
except ImportError:
    pass


# ============================================================
# 项目路径 — 所有数据保存在项目内
# ============================================================
BASE_DIR = Path(__file__).parent.parent
BACKEND_DIR = BASE_DIR / "backend"
DATA_DIR = BACKEND_DIR / "data"
MODELS_DIR = BACKEND_DIR / "ai_models" / "models"
DB_PATH = DATA_DIR / "quant_trader.db"
CACHE_DIR = BASE_DIR / "cache"
LOGS_DIR = BASE_DIR / "logs"
TORCH_CACHE = CACHE_DIR / "torch"
HF_CACHE = CACHE_DIR / "huggingface"
YF_CACHE = CACHE_DIR / "yfinance"

# 确保所有目录存在
for d in [DATA_DIR, MODELS_DIR, CACHE_DIR, LOGS_DIR, TORCH_CACHE, HF_CACHE, YF_CACHE]:
    d.mkdir(parents=True, exist_ok=True)

# 重定向外部缓存到项目内
os.environ.setdefault("TORCH_HOME", str(TORCH_CACHE))
os.environ.setdefault("HF_HOME", str(HF_CACHE))


# ============================================================
# 市场配置
# ============================================================
MARKET_CONFIGS = {
    "US": {
        "timezone": "US/Eastern",
        "open": "09:30", "close": "16:00",
        "currency": "USD",
    },
    "HK": {
        "timezone": "Asia/Hong_Kong",
        "open": "09:30", "close": "16:00",
        "currency": "HKD",
    },
    "SG": {
        "timezone": "Asia/Singapore",
        "open": "09:00", "close": "17:00",
        "currency": "SGD",
    },
    "AU": {
        "timezone": "Australia/Sydney",
        "open": "10:00", "close": "16:00",
        "currency": "AUD",
    },
    "NZ": {
        "timezone": "Pacific/Auckland",
        "open": "10:00", "close": "16:45",
        "currency": "NZD",
    },
}


# ============================================================
# 数据配置
# ============================================================
@dataclass
class DataConfig:
    """数据获取配置"""
    US_TICKERS: List[str] = field(default_factory=lambda: [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",
        "META", "TSLA", "JPM", "V", "SPY",
    ])
    HK_TICKERS: List[str] = field(default_factory=lambda: [
        "00700", "09988", "03690", "09999",
        "01810", "00941", "00883", "01299",
    ])
    SG_TICKERS: List[str] = field(default_factory=lambda: [
        "D05.SI", "O39.SI", "U11.SI", "Z74.SI",
        "C52.SI", "C6L.SI", "S58.SI", "BS6.SI",
    ])
    AU_TICKERS: List[str] = field(default_factory=lambda: [
        "BHP.AX", "CBA.AX", "CSL.AX", "NAB.AX",
        "WBC.AX", "ANZ.AX", "MQG.AX", "WES.AX",
    ])
    NZ_TICKERS: List[str] = field(default_factory=lambda: [
        "FPH.NZ", "AIA.NZ", "MEL.NZ", "SPK.NZ",
        "ATM.NZ", "MCY.NZ", "IFT.NZ", "EBO.NZ",
    ])

    @property
    def ALL_TICKERS(self):
        _hk_map = {"00700":"0700","09988":"9988","03690":"3690","09999":"9999",
                   "01810":"1810","00941":"0941","00883":"0883","01299":"1299"}
        return self.US_TICKERS + [f"{_hk_map.get(t,t)}.HK" for t in self.HK_TICKERS] \
               + self.SG_TICKERS + self.AU_TICKERS + self.NZ_TICKERS

    @property
    def TICKER_INFO(self):
        _hk_map = {"00700":"0700","09988":"9988","03690":"3690","09999":"9999",
                   "01810":"1810","00941":"0941","00883":"0883","01299":"1299"}
        result = []
        for t in self.US_TICKERS:
            result.append({"symbol": t, "name": t, "market": "US", "currency": "USD"})
        for t in self.HK_TICKERS:
            result.append({"symbol": f"{_hk_map.get(t,t)}.HK", "name": t, "market": "HK", "currency": "HKD"})
        for t in self.SG_TICKERS:
            result.append({"symbol": t, "name": t.replace(".SI",""), "market": "SG", "currency": "SGD"})
        for t in self.AU_TICKERS:
            result.append({"symbol": t, "name": t.replace(".AX",""), "market": "AU", "currency": "AUD"})
        for t in self.NZ_TICKERS:
            result.append({"symbol": t, "name": t.replace(".NZ",""), "market": "NZ", "currency": "NZD"})
        return result

    BENCHMARK: str = "SPY"
    HISTORY_DAYS: int = 730
    UPDATE_INTERVAL: int = 60
    USD_HKD_RATE: float = 7.82


# ============================================================
# AI 模型配置
# ============================================================
@dataclass
class ModelConfig:
    TRANSFORMER_LOOKBACK: int = 60
    TRANSFORMER_PREDICTION_DAYS: List[int] = field(default_factory=lambda: [1, 5, 20])
    TRANSFORMER_D_MODEL: int = 128
    TRANSFORMER_N_HEADS: int = 8
    TRANSFORMER_N_LAYERS: int = 4
    TRANSFORMER_DROPOUT: float = 0.1
    TRANSFORMER_EPOCHS: int = 20
    TRANSFORMER_BATCH_SIZE: int = 64
    TRANSFORMER_LEARNING_RATE: float = 1e-4

    RL_LEARNING_RATE: float = 3e-4
    RL_N_STEPS: int = 2048
    RL_BATCH_SIZE: int = 64
    RL_GAMMA: float = 0.99
    RL_GAE_LAMBDA: float = 0.95
    RL_CLIP_RANGE: float = 0.2
    RL_ENT_COEF: float = 0.01
    RL_TOTAL_TIMESTEPS: int = 30000
    RL_MAX_TRADE_PERCENT: float = 0.2

    SENTIMENT_MODEL: str = "ProsusAI/finbert"
    SENTIMENT_MAX_LENGTH: int = 512

    ENSEMBLE_WEIGHTS: dict = field(default_factory=lambda: {
        "transformer": 0.55, "rl_agent": 0.00,
        "sentiment": 0.15, "technical": 0.30,
    })

    RETRAIN_INTERVAL_DAYS: int = 7
    WALK_FORWARD_WINDOW: int = 252
    VALIDATION_SPLIT: float = 0.2


# ============================================================
# 交易配置
# ============================================================
@dataclass
class TradingConfig:
    INITIAL_CAPITAL: float = 1_000_000.0
    BASE_CURRENCY: str = "USD"
    SIMULATION_MODE: bool = True

    # Multi-currency conversion rates to USD
    CURRENCY_RATES: dict = field(default_factory=lambda: {
        "USD": 1.0,
        "HKD": 0.128,   # 1 HKD ≈ 0.128 USD
        "SGD": 0.75,    # 1 SGD ≈ 0.75 USD
        "AUD": 0.67,    # 1 AUD ≈ 0.67 USD
        "NZD": 0.62,    # 1 NZD ≈ 0.62 USD
    })

    MAX_POSITION_SIZE: float = 0.20
    MAX_PORTFOLIO_RISK: float = 0.03
    STOP_LOSS_PCT: float = 0.05
    TAKE_PROFIT_PCT: float = 0.15
    MAX_DRAWDOWN: float = 0.25
    VAR_CONFIDENCE: float = 0.95
    COMMISSION_RATE: float = 0.001
    SLIPPAGE: float = 0.0005
    MIN_CONFIDENCE: float = 0.15
    MIN_TRADE_VALUE: float = 1000.0
    MIN_SHARES: int = 1

    TIGER_ID: str = field(default_factory=lambda: os.getenv("TIGER_ID", ""))
    TIGER_PRIVATE_KEY: str = field(default_factory=lambda: os.getenv("TIGER_PRIVATE_KEY", ""))
    TIGER_ACCOUNT: str = field(default_factory=lambda: os.getenv("TIGER_ACCOUNT", ""))
    TIGER_PAPER_TRADING: bool = field(default_factory=lambda: os.getenv("TIGER_PAPER_TRADING", "true").lower() == "true")
    TIGER_CONFIG_DIR: str = field(default_factory=lambda: os.getenv("TIGER_CONFIG_DIR", "~/.tigeropen"))


# ============================================================
# API & 前端配置
# ============================================================
@dataclass
class APIConfig:
    HOST: str = "0.0.0.0"
    PORT: int = 8001
    RELOAD: bool = True
    CORS_ORIGINS: List[str] = field(default_factory=lambda: [
        "http://localhost:5180", "http://localhost:3000",
    ])


# ============================================================
# 全局单例
# ============================================================
data_config = DataConfig()
model_config = ModelConfig()
trading_config = TradingConfig()
api_config = APIConfig()
