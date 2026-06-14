"""services/execution_service/execution/twap.py – Time-Weighted Average Price execution.

Splits order into N equal time slices. Configurable interval (5/15/30 min).
"""

from __future__ import annotations

from services.execution_service.execution.algo_base import ExecutionAlgorithm
from services.execution_service.config import exec_config


class TWAPExecutor(ExecutionAlgorithm):
    """TWAP execution: equal time slices.

    Attributes:
        n_slices: Number of time slices.
        interval_seconds: Seconds between slices.
        total_duration: Total execution duration in seconds.
    """

    def __init__(
        self,
        total_quantity: int,
        side: str,
        ticker: str = "",
        n_slices: int | None = None,
        interval_seconds: int | None = None,
    ) -> None:
        super().__init__(total_quantity, side, ticker)
        self.algo_name = "twap"
        self.n_slices = n_slices or exec_config.TWAP_DEFAULT_INTERVALS
        self.interval_seconds = interval_seconds or exec_config.TWAP_INTERVAL_SECONDS
        self.total_duration = self.n_slices * self.interval_seconds

    def schedule(self, **kwargs) -> list[tuple[float, float]]:
        """Generate TWAP schedule.

        Returns:
            List of (1/n_slices, interval_seconds) tuples.
        """
        fraction = 1.0 / max(self.n_slices, 1)
        self.slices = [(fraction, self.interval_seconds)] * self.n_slices
        return self.slices

    def get_slice_quantity(self) -> int:
        """Get quantity for each slice (equal split).

        Returns:
            Shares per slice.
        """
        return max(1, self.total_quantity // self.n_slices)

    @staticmethod
    def describe() -> dict:
        """Return configuration description."""
        return {
            "algo": "twap",
            "description": "Time-Weighted Average Price",
            "default_slices": exec_config.TWAP_DEFAULT_INTERVALS,
            "default_interval_seconds": exec_config.TWAP_INTERVAL_SECONDS,
        }
