"""
DailyState — lightweight per-session state tracker
====================================================
Tracks trade date, daily-start portfolio value, and the
intra-day trade counter.  Used by the pipeline to detect
date rolls and anchor the day's reference valuation.

Zero ``import backend.`` — fully self-contained.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from loguru import logger


class DailyState:
    """Per-trading-day book-keeping values.

    Attributes:
        trade_date: ISO-format date string for the current trading day.
        daily_start_value: Portfolio value at the start of the day (USD).
        trades_today: Number of trades executed today.
    """

    def __init__(self, daily_start_value: float = 0.0) -> None:
        self.trade_date: str = datetime.now().strftime("%Y-%m-%d")
        self.daily_start_value: float = daily_start_value
        self.trades_today: int = 0

    # ── Date-roll detection ──────────────────────────────────

    def check_date_roll(self) -> bool:
        """Check whether the date has rolled since the last call.

        Returns:
            True when ``today != self.trade_date`` (new trading day).
        """
        today: str = datetime.now().strftime("%Y-%m-%d")
        if today != self.trade_date:
            logger.info(f"📅 Trading-day rollover: {self.trade_date} → {today}")
            return True
        return False

    def reset_for_new_day(self, portfolio_value: float) -> None:
        """Reset all day-anchored state for a fresh trading day.

        Args:
            portfolio_value: Current portfolio total value, used as
                the new ``daily_start_value``.
        """
        self.trade_date = datetime.now().strftime("%Y-%m-%d")
        self.daily_start_value = portfolio_value
        self.trades_today = 0
        logger.info(
            f"📅 DailyState reset: date={self.trade_date}, "
            f"start_value=${portfolio_value:,.2f}"
        )

    def record_trade(self) -> None:
        """Increment the daily trade counter."""
        self.trades_today += 1

    def get_snapshot(self) -> Dict[str, Any]:
        """Return a lightweight dict for logging / WS push."""
        return {
            "trade_date": self.trade_date,
            "daily_start_value": round(self.daily_start_value, 2),
            "trades_today": self.trades_today,
        }
