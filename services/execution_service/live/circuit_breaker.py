"""services/execution_service/live/circuit_breaker.py – Risk circuit breakers.

Three rules:
1. Daily loss (realized + unrealized) ≥ 5% → halt trading until next day
2. Single order would risk ≥ 2% of portfolio → reject
3. 3 consecutive losing trades → 30-minute cool-down
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from services.execution_service.config import exec_config


class CircuitBreaker:
    """Trading circuit breaker for risk management.

    Attributes:
        daily_loss_limit: Maximum allowed daily loss as fraction of NAV.
        single_order_limit: Maximum single-order risk as fraction of NAV.
        cooling_minutes: Cool-down period after 3 consecutive losses.
        consecutive_loss_limit: Number of consecutive losses to trigger cool-down.
    """

    def __init__(
        self,
        daily_loss_limit: float | None = None,
        single_order_limit: float | None = None,
        cooling_minutes: int | None = None,
        consecutive_loss_limit: int | None = None,
    ) -> None:
        self.daily_loss_limit = daily_loss_limit or exec_config.CB_DAILY_LOSS_LIMIT_PCT
        self.single_order_limit = single_order_limit or exec_config.CB_SINGLE_ORDER_LIMIT_PCT
        self.cooling_minutes = cooling_minutes or exec_config.CB_COOLING_MINUTES
        self.consecutive_loss_limit = consecutive_loss_limit or exec_config.CB_CONSECUTIVE_LOSS_LIMIT

        self._day_start_nav: float = 0.0
        self._current_nav: float = 0.0
        self._consecutive_losses: int = 0
        self._cooling_until: float = 0.0
        self._halted: bool = False
        self._halt_reason: str = ""
        self._last_reset_date: str = ""

    def set_nav(self, nav: float) -> None:
        """Set current NAV and initialize day tracking.

        Args:
            nav: Current net asset value.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._last_reset_date:
            self._day_start_nav = nav
            self._last_reset_date = today
            self._halted = False
            self._halt_reason = ""
            self._consecutive_losses = 0
        self._current_nav = nav

    def allow_order(self, ticker: str, quantity: int, price: float | None = None) -> bool:
        """Check if an order is allowed under current rules.

        Args:
            ticker: Stock ticker.
            quantity: Order quantity.
            price: Estimated fill price.

        Returns:
            True if order is allowed.
        """
        # Rule 1: Daily loss halt
        if self._halted:
            logger.warning(f"Circuit breaker HALTED: {self._halt_reason}")
            return False

        # Rule 1: Check daily loss
        if self._day_start_nav > 0:
            daily_loss = (self._day_start_nav - self._current_nav) / self._day_start_nav
            if daily_loss >= self.daily_loss_limit:
                self._halted = True
                self._halt_reason = f"Daily loss limit: {daily_loss:.2%} >= {self.daily_loss_limit:.2%}"
                logger.warning(self._halt_reason)
                return False

        # Rule 2: Single order risk
        if price and self._current_nav > 0:
            order_value = quantity * price
            order_risk = order_value / self._current_nav
            if order_risk > self.single_order_limit:
                logger.warning(f"Order risk {order_risk:.2%} exceeds limit {self.single_order_limit:.2%}")
                return False

        # Rule 3: Cool-down check
        now = time.time()
        if now < self._cooling_until:
            remaining = (self._cooling_until - now) / 60
            logger.warning(f"Cool-down active: {remaining:.0f} minutes remaining")
            return False

        return True

    def record_trade(self, pnl: float) -> None:
        """Record a completed trade for loss tracking.

        Args:
            pnl: Profit/loss of the trade.
        """
        if pnl < 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

        if self._consecutive_losses >= self.consecutive_loss_limit:
            self._cooling_until = time.time() + self.cooling_minutes * 60
            logger.warning(
                f"Cool-down activated: {self._consecutive_losses} "
                f"consecutive losses, cooling for {self.cooling_minutes} min"
            )

    def reset(self) -> None:
        """Manually reset all circuit breakers."""
        self._halted = False
        self._halt_reason = ""
        self._consecutive_losses = 0
        self._cooling_until = 0.0
        logger.info("Circuit breaker reset")

    def status(self) -> dict[str, Any]:
        """Get circuit breaker status.

        Returns:
            Status dictionary.
        """
        now = time.time()
        return {
            "halted": self._halted,
            "halt_reason": self._halt_reason,
            "consecutive_losses": self._consecutive_losses,
            "cooling_active": now < self._cooling_until,
            "cooling_remaining_minutes": max(0, (self._cooling_until - now) / 60),
            "daily_loss_pct": (
                (self._day_start_nav - self._current_nav) / self._day_start_nav * 100
                if self._day_start_nav > 0 else 0.0
            ),
        }
