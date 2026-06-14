"""configs/risk_limits.py – Risk control parameters for Quant AI Trader v2.

Defines position limits, stop-loss thresholds, VaR parameters, circuit-breaker
thresholds, and portfolio-level risk constraints for institutional-grade trading.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RiskLimitGroup(str, Enum):
    """Risk limit categories."""
    POSITION = "position"
    PORTFOLIO = "portfolio"
    EXECUTION = "execution"
    MARKET = "market"


@dataclass(frozen=True)
class RiskLimits:
    """Immutable risk parameter set for the trading system."""

    # ── Position-Level Limits ────────────────────────────────
    MAX_POSITION_SIZE: float = field(
        default=0.20,
        metadata={"description": "Maximum position as fraction of portfolio NAV"}
    )
    MAX_SINGLE_STOCK_EXPOSURE: float = field(
        default=0.15,
        metadata={"description": "Max single stock exposure (% portfolio)"}
    )
    MAX_SECTOR_EXPOSURE: float = field(
        default=0.35,
        metadata={"description": "Max sector concentration (% portfolio)"}
    )
    MAX_MARKET_EXPOSURE: float = field(
        default=0.60,
        metadata={"description": "Max exposure to single market (% portfolio)"}
    )
    MAX_GROSS_EXPOSURE: float = field(
        default=2.50,
        metadata={"description": "Max gross leverage (long+short)/NAV"}
    )
    MAX_NET_EXPOSURE: float = field(
        default=1.50,
        metadata={"description": "Max net exposure (long-short)/NAV"}
    )

    # ── Stop-Loss / Drawdown ─────────────────────────────────
    STOP_LOSS: float = field(
        default=0.05,
        metadata={"description": "Single-position stop-loss (% loss from entry)"}
    )
    TRAILING_STOP: float = field(
        default=0.08,
        metadata={"description": "Trailing stop (% from peak)"}
    )
    MAX_DRAWDOWN_PORTFOLIO: float = field(
        default=0.15,
        metadata={"description": "Max portfolio drawdown trigger"}
    )
    DAILY_LOSS_LIMIT: float = field(
        default=0.03,
        metadata={"description": "Max daily PnL loss (% of NAV)"}
    )
    WEEKLY_LOSS_LIMIT: float = field(
        default=0.06,
        metadata={"description": "Max weekly PnL loss (% of NAV)"}
    )
    MONTHLY_LOSS_LIMIT: float = field(
        default=0.10,
        metadata={"description": "Max monthly PnL loss (% of NAV)"}
    )

    # ── VaR / Risk Metrics ──────────────────────────────────
    VAR_CONF: float = field(
        default=0.95,
        metadata={"description": "Value-at-Risk confidence level"}
    )
    VAR_HORIZON_DAYS: int = field(
        default=1,
        metadata={"description": "VaR calculation horizon in days"}
    )
    VAR_LIMIT: float = field(
        default=0.02,
        metadata={"description": "Daily VaR limit (% of NAV)"}
    )
    CVAR_CONF: float = field(
        default=0.95,
        metadata={"description": "Conditional VaR (Expected Shortfall) confidence"}
    )
    CVAR_LIMIT: float = field(
        default=0.03,
        metadata={"description": "Daily CVaR limit (% of NAV)"}
    )
    STRESS_VAR_MULTIPLIER: float = field(
        default=3.0,
        metadata={"description": "Stress VaR multiplier on historical worst"}
    )

    # ── Circuit Breakers ─────────────────────────────────────
    CIRCUIT_BREAKER_DAILY_LOSS: float = field(
        default=0.05,
        metadata={"description": "Halt all trading if daily loss exceeds this"}
    )
    CIRCUIT_BREAKER_DRAWDOWN: float = field(
        default=0.10,
        metadata={"description": "Halt trading at this portfolio drawdown"}
    )
    CIRCUIT_BREAKER_VOLATILITY: float = field(
        default=0.04,
        metadata={"description": "Halt if VIX-equivalent > this level"}
    )
    CIRCUIT_BREAKER_CORRELATION: float = field(
        default=0.90,
        metadata={"description": "Halt if cross-sectional correlation exceeds"}
    )
    COOLING_OFF_MINUTES: int = field(
        default=15,
        metadata={"description": "Cooling-off period after circuit breaker (minutes)"}
    )

    # ── Leverage / Margin ───────────────────────────────────
    INITIAL_MARGIN_RATE: float = field(
        default=0.50,
        metadata={"description": "Reg T initial margin (50%)"}
    )
    MAINTENANCE_MARGIN_RATE: float = field(
        default=0.25,
        metadata={"description": "Maintenance margin requirement"}
    )
    MARGIN_CALL_THRESHOLD: float = field(
        default=0.30,
        metadata={"description": "Trigger margin call below this equity ratio"}
    )

    # ── Liquidity Limits ─────────────────────────────────────
    MAX_ORDER_PARTICIPATION: float = field(
        default=0.05,
        metadata={"description": "Max order as fraction of ADV (Average Daily Volume)"}
    )
    MAX_ORDER_PARTICIPATION_MINUTE: float = field(
        default=0.10,
        metadata={"description": "Max order as fraction of 1-min volume"}
    )
    MIN_ADV_THRESHOLD: float = field(
        default=1_000_000.0,
        metadata={"description": "Minimum ADV in USD to trade a stock"}
    )
    MAX_SPREAD_BPS: float = field(
        default=50.0,
        metadata={"description": "Max allowed bid-ask spread (bps)"}
    )

    # ── Execution Risk ─────────────────────────────────────
    MAX_SLIPPAGE_BPS: float = field(
        default=10.0,
        metadata={"description": "Max allowed execution slippage (bps)"}
    )
    ORDER_TIMEOUT_SECONDS: int = field(
        default=30,
        metadata={"description": "Order timeout before cancellation"}
    )
    MAX_RETRY_ATTEMPTS: int = field(
        default=3,
        metadata={"description": "Max order retry attempts on failure"}
    )
    MIN_FILL_RATIO: float = field(
        default=0.90,
        metadata={"description": "Minimum acceptable fill ratio per order"}
    )

    # ── Market-Specific ─────────────────────────────────────
    US_TRADING_HOURS_ONLY: bool = field(
        default=True,
        metadata={"description": "Restrict US trading to regular hours only"}
    )
    PRE_MARKET_ALLOWED: bool = field(
        default=False,
        metadata={"description": "Allow pre-market trading"}
    )
    AFTER_HOURS_ALLOWED: bool = field(
        default=False,
        metadata={"description": "Allow after-hours trading"}
    )

    # ── Factor Limits ───────────────────────────────────────
    MAX_FACTOR_EXPOSURE: float = field(
        default=3.0,
        metadata={"description": "Max exposure to a single factor (z-score)"}
    )
    MAX_STYLE_FACTOR_DEVIATION: float = field(
        default=0.3,
        metadata={"description": "Max deviation from benchmark style factors"}
    )

    # ── Cash Management ─────────────────────────────────────
    MIN_CASH_BUFFER: float = field(
        default=0.05,
        metadata={"description": "Minimum cash buffer (% of NAV)"}
    )
    MAX_CASH_WEIGHT: float = field(
        default=0.25,
        metadata={"description": "Maximum cash weight (% of NAV) before reinvestment"}
    )


# Singleton instance
RISK_LIMITS = RiskLimits()


def get_limit(attr_name: str) -> float | int | bool:
    """Safely retrieve a risk limit by attribute name.

    Args:
        attr_name: The RiskLimits attribute name (e.g. 'MAX_POSITION_SIZE').

    Returns:
        The limit value.

    Raises:
        AttributeError: If the attribute does not exist.
    """
    if not hasattr(RISK_LIMITS, attr_name):
        raise AttributeError(f"Risk limit '{attr_name}' not found in RiskLimits")
    return getattr(RISK_LIMITS, attr_name)


def get_all_position_limits() -> dict[str, float]:
    """Return all position-level risk limits."""
    return {
        "MAX_POSITION_SIZE": RISK_LIMITS.MAX_POSITION_SIZE,
        "MAX_SINGLE_STOCK_EXPOSURE": RISK_LIMITS.MAX_SINGLE_STOCK_EXPOSURE,
        "MAX_SECTOR_EXPOSURE": RISK_LIMITS.MAX_SECTOR_EXPOSURE,
        "MAX_MARKET_EXPOSURE": RISK_LIMITS.MAX_MARKET_EXPOSURE,
        "MAX_GROSS_EXPOSURE": RISK_LIMITS.MAX_GROSS_EXPOSURE,
        "MAX_NET_EXPOSURE": RISK_LIMITS.MAX_NET_EXPOSURE,
    }


def get_stop_loss_limits() -> dict[str, float]:
    """Return all stop-loss and drawdown limits."""
    return {
        "STOP_LOSS": RISK_LIMITS.STOP_LOSS,
        "TRAILING_STOP": RISK_LIMITS.TRAILING_STOP,
        "MAX_DRAWDOWN_PORTFOLIO": RISK_LIMITS.MAX_DRAWDOWN_PORTFOLIO,
        "DAILY_LOSS_LIMIT": RISK_LIMITS.DAILY_LOSS_LIMIT,
        "WEEKLY_LOSS_LIMIT": RISK_LIMITS.WEEKLY_LOSS_LIMIT,
        "MONTHLY_LOSS_LIMIT": RISK_LIMITS.MONTHLY_LOSS_LIMIT,
    }
