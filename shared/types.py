"""shared/types.py – Core type aliases, enums, and constants for Quant AI Trader v2.

Centralizes all domain-specific types to avoid circular imports and
ensure consistency across the codebase.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal, TypeAlias

# ── Market Enum ──────────────────────────────────────────────
class Market(str, Enum):
    """Supported markets."""
    US = "US"
    HK = "HK"
    SG = "SG"
    AU = "AU"
    NZ = "NZ"


# ── Signal Direction ─────────────────────────────────────────
class SignalDirection(int, Enum):
    """Trading signal direction."""
    LONG = 1
    FLAT = 0
    SHORT = -1


# ── Order Types ──────────────────────────────────────────────
class OrderType(str, Enum):
    """Order type enumeration."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"
    TWAP = "TWAP"
    VWAP = "VWAP"
    ICEBERG = "ICEBERG"


class OrderSide(str, Enum):
    """Order side enumeration."""
    BUY = "BUY"
    SELL = "SELL"
    SELL_SHORT = "SELL_SHORT"
    COVER = "COVER"


class OrderStatus(str, Enum):
    """Order lifecycle status."""
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIAL_FILL = "PARTIAL_FILL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class TimeInForce(str, Enum):
    """Time-in-force for orders."""
    DAY = "DAY"
    GTC = "GTC"  # Good Till Cancelled
    IOC = "IOC"  # Immediate Or Cancel
    FOK = "FOK"  # Fill Or Kill


# ── Factor Category ──────────────────────────────────────────
class FactorCategory(str, Enum):
    """Factor category enumeration."""
    TECHNICAL = "technical"
    FUNDAMENTAL = "fundamental"
    ALTERNATIVE = "alternative"
    MICROSTRUCTURE = "microstructure"


# ── Model Type ───────────────────────────────────────────────
class ModelType(str, Enum):
    """Supported model types."""
    XGBOOST = "xgboost"
    LIGHTGBM = "lightgbm"
    CATBOOST = "catboost"
    ENSEMBLE = "ensemble"
    NEURAL_NET = "neural_network"
    LINEAR = "linear"


class ModelStatus(str, Enum):
    """Model lifecycle status."""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    ARCHIVED = "archived"


# ── Asset Class ──────────────────────────────────────────────
class AssetClass(str, Enum):
    """Financial asset classes."""
    EQUITY = "equity"
    ETF = "etf"
    FUTURE = "future"
    OPTION = "option"
    FX = "fx"
    CRYPTO = "crypto"


# ── Execution Mode ───────────────────────────────────────────
class ExecutionMode(str, Enum):
    """Execution environment mode."""
    PAPER = "paper"
    LIVE = "live"
    BACKTEST = "backtest"


# ── Alert Severity ───────────────────────────────────────────
class AlertSeverity(str, Enum):
    """Alert severity levels."""
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class AlertType(str, Enum):
    """Alert type categories."""
    RISK = "RISK"
    EXECUTION = "EXECUTION"
    DATA = "DATA"
    MODEL = "MODEL"
    SYSTEM = "SYSTEM"


# ── Corporate Action Type ────────────────────────────────────
class CorporateActionType(str, Enum):
    """Corporate action types."""
    SPLIT = "SPLIT"
    DIVIDEND = "DIVIDEND"
    MERGER = "MERGER"
    SPINOFF = "SPINOFF"
    RIGHTS = "RIGHTS"
    BUYBACK = "BUYBACK"


# ── Cash Flow Type ───────────────────────────────────────────
class CashFlowType(str, Enum):
    """Cash flow categories."""
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    DIVIDEND = "DIVIDEND"
    INTEREST = "INTEREST"
    COMMISSION = "COMMISSION"
    TAX = "TAX"
    OTHER = "OTHER"


# ── Prediction Horizon ───────────────────────────────────────
PredictionHorizon: TypeAlias = Literal["1d", "5d", "21d", "63d", "252d"]


# ── Factor Frequency ─────────────────────────────────────────
FactorFrequency: TypeAlias = Literal["intraday", "daily", "weekly", "biweekly", "monthly", "quarterly", "annually"]


# ── Core Type Aliases ────────────────────────────────────────
Ticker: TypeAlias = str
DateStr: TypeAlias = str  # ISO format date string
Timestamp: TypeAlias = datetime
TradeDate: TypeAlias = date
NAV: TypeAlias = float
Weight: TypeAlias = float  # 0.0 to 1.0
Price: TypeAlias = float
Volume: TypeAlias = int
FactorValue: TypeAlias = float
ReturnValue: TypeAlias = float
CorrelationValue: TypeAlias = float  # -1.0 to 1.0
JSONDict: TypeAlias = dict[str, Any]
JSONList: TypeAlias = list[Any]
