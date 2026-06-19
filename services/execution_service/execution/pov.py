"""services/execution_service/execution/pov.py – Percentage of Volume execution.

Controls participation rate ≤ specified percentage of market volume.
Default: 20% of market volume per slice.
"""

from __future__ import annotations

from services.execution_service.execution.algo_base import ExecutionAlgorithm
from services.execution_service.config import exec_config


class POVExecutor(ExecutionAlgorithm):
    """POV execution: percentage of market volume.

    Adapts to changing market volume — higher volume = faster execution.

    Attributes:
        target_rate: Target participation rate (e.g. 0.20 = 20% of market volume).
        max_slices: Maximum number of slices.
        interval_seconds: Seconds between slices.
    """

    def __init__(
        self,
        total_quantity: int,
        side: str,
        ticker: str = "",
        target_rate: float | None = None,
        interval_seconds: int = 300,
    ) -> None:
        super().__init__(total_quantity, side, ticker)
        self.algo_name = "pov"
        self.target_rate = target_rate or exec_config.POV_DEFAULT_PARTICIPATION
        self.interval_seconds = interval_seconds
        self.max_slices = 100

    def schedule(self, **kwargs) -> list[tuple[float, float]]:
        """Generate dynamic POV schedule.

        Since POV adapts to market volume, the schedule provides
        maximum allowed participation, not fixed slices.

        Returns:
            List of (target_rate, interval) tuples.
        """
        # POV doesn't have fixed fractions — it adapts dynamically
        # We return the maximum participation rate as a guide
        self.slices = [(self.target_rate, self.interval_seconds)] * self.max_slices
        return self.slices

    def compute_slice_quantity(self, market_volume: int) -> int:
        """Compute dynamic slice size based on market volume.

        Args:
            market_volume: Current market volume in the trading window.

        Returns:
            Quantity for this slice.
        """
        remaining = self.remaining_quantity()
        if remaining <= 0:
            return 0

        # Target: min(target_rate * market_volume, remaining)
        target_qty = int(market_volume * self.target_rate)
        return max(1, min(target_qty, remaining))

    def estimate_duration(self, avg_daily_volume: int) -> float:
        """Estimate total execution time in seconds.

        Args:
            avg_daily_volume: Average daily trading volume.

        Returns:
            Estimated duration in seconds.
        """
        if avg_daily_volume <= 0:
            return float("inf")

        daily_participation = self.total_quantity / avg_daily_volume
        slices_needed = daily_participation / max(self.target_rate, 0.001)
        return slices_needed * self.interval_seconds

    @staticmethod
    def describe() -> dict:
        return {
            "algo": "pov",
            "description": "Percentage of Volume",
            "default_participation_rate": exec_config.POV_DEFAULT_PARTICIPATION,
            "participation_rate": "Controls percentage of market volume consumed per slice",
        }
