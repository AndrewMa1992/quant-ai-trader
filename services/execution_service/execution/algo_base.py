"""services/execution_service/execution/algo_base.py – Execution algorithm abstract base.

All execution algorithms must implement:
- schedule() → list of (timestamp, quantity) slices
- execute() → list of FillEvent
Supports progress tracking and emergency cancellation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any


class ExecutionAlgorithm(ABC):
    """Abstract base for execution algorithms (TWAP, VWAP, POV, etc.).

    Attributes:
        algo_name: Human-readable algorithm name.
        total_quantity: Total shares to execute.
        side: 'BUY' or 'SELL'.
        slices: List of (slice_ratio, timestamp) tuples.
        is_cancelled: Emergency cancel flag.
        completed_quantity: Shares executed so far.
    """

    def __init__(
        self,
        total_quantity: int,
        side: str,
        ticker: str = "",
    ) -> None:
        self.algo_name: str = "base"
        self.total_quantity = total_quantity
        self.side = side.upper()
        self.ticker = ticker
        self.slices: list[tuple[float, float]] = []  # (fraction, delay_seconds)
        self.is_cancelled: bool = False
        self.completed_quantity: int = 0
        self.start_time: datetime | None = None

    @abstractmethod
    def schedule(self, **kwargs: Any) -> list[tuple[float, float]]:
        """Generate execution schedule.

        Returns:
            List of (fraction_of_total, delay_seconds) tuples.
        """
        ...

    def cancel(self) -> None:
        """Emergency cancel remaining slices."""
        self.is_cancelled = True

    def progress(self) -> float:
        """Return execution progress as fraction [0, 1].

        Returns:
            Completed fraction.
        """
        if self.total_quantity <= 0:
            return 1.0
        return min(self.completed_quantity / self.total_quantity, 1.0)

    def remaining_quantity(self) -> int:
        """Get remaining shares to execute.

        Returns:
            Remaining quantity.
        """
        return max(0, self.total_quantity - self.completed_quantity)

    def record_fill(self, quantity: int) -> None:
        """Record a partial fill.

        Args:
            quantity: Shares filled.
        """
        self.completed_quantity += quantity

    def get_next_slice_quantity(self) -> int:
        """Get quantity for the next slice.

        Returns:
            Next slice size in shares.
        """
        remaining = self.remaining_quantity()
        if remaining <= 0:
            return 0

        # Default: equal split of remaining
        slices_left = len([s for s in self.slices if s[1] > 0]) or 1
        return max(1, remaining // slices_left)

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__}(ticker={self.ticker}, "
            f"side={self.side}, qty={self.total_quantity}, "
            f"progress={self.progress():.1%})>"
        )
