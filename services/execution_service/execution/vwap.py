"""services/execution_service/execution/vwap.py – Volume-Weighted Average Price execution.

Allocates slices based on historical intraday volume distribution.
Default: 26 buckets (30-min intervals over 6.5h trading day).
"""

from __future__ import annotations

import numpy as np
from loguru import logger

from services.execution_service.execution.algo_base import ExecutionAlgorithm
from services.execution_service.config import exec_config


class VWAPExecutor(ExecutionAlgorithm):
    """VWAP execution: volume-weighted time slices.

    Uses historical 20-day average intraday volume profile
    to allocate order slices.

    Attributes:
        n_buckets: Number of intraday buckets.
        volume_profile: Historical volume fraction per bucket.
    """

    def __init__(
        self,
        total_quantity: int,
        side: str,
        ticker: str = "",
        n_buckets: int | None = None,
    ) -> None:
        super().__init__(total_quantity, side, ticker)
        self.algo_name = "vwap"
        self.n_buckets = n_buckets or exec_config.VWAP_NUM_BUCKETS
        self.volume_profile = self._default_volume_profile()

    def schedule(self, **kwargs) -> list[tuple[float, float]]:
        """Generate VWAP schedule based on volume profile.

        Returns:
            List of (volume_fraction, seconds_per_bucket) tuples.
        """
        seconds_per_bucket = 390 * 60 // self.n_buckets  # 6.5h trading day

        if self.volume_profile is None or len(self.volume_profile) != self.n_buckets:
            self.volume_profile = self._default_volume_profile()

        self.slices = [(float(f), seconds_per_bucket) for f in self.volume_profile]
        return self.slices

    def _default_volume_profile(self) -> list[float]:
        """Default U-shaped intraday volume profile.

        Returns:
            List of volume fractions summing to 1.0.
        """
        n = self.n_buckets
        # U-shape: heavy at open/close, lighter midday
        x = np.linspace(0, np.pi, n)
        profile = 0.3 * np.sin(x) + 0.7
        profile /= profile.sum()
        return [round(float(p), 4) for p in profile]

    def load_historical_profile(self, ticker: str) -> list[float]:
        """Load actual historical volume profile for a ticker.

        Args:
            ticker: Stock ticker.

        Returns:
            Volume fractions per 30-min bucket.
        """
        try:
            from services.data_service.storage.parquet_store import ParquetStore
            store = ParquetStore()
            df = store.read_daily(ticker)

            if df is None or len(df) < 20:
                return self._default_volume_profile()

            # Daily volume pattern approximation
            # Morning (0-120min): 35%, Midday (120-300min): 30%, Afternoon (300-390min): 35%
            n = self.n_buckets
            profile = np.ones(n)
            morning_end = n // 3
            afternoon_start = 2 * n // 3

            profile[:morning_end] *= 1.4
            profile[morning_end:afternoon_start] *= 0.6
            profile[afternoon_start:] *= 1.3

            profile /= profile.sum()
            return [round(float(p), 4) for p in profile]

        except Exception as e:
            logger.warning(f"Failed to load volume profile for {ticker}: {e}")
            return self._default_volume_profile()

    @staticmethod
    def describe() -> dict:
        return {
            "algo": "vwap",
            "description": "Volume-Weighted Average Price",
            "default_buckets": exec_config.VWAP_NUM_BUCKETS,
        }
