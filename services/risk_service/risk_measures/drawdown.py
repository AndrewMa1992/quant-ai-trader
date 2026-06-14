"""services/risk_service/risk_measures/drawdown.py – Drawdown analysis.

Measures:
- Maximum drawdown (peak-to-trough)
- Drawdown duration (time underwater)
- Drawdown recovery analysis
- Rolling maximum drawdown
- Underwater curve
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from services.data_service.storage.parquet_store import ParquetStore


class DrawdownAnalyzer:
    """Analyzes drawdown characteristics of a price series.

    Drawdown at time t: DD(t) = (peak(t) - value(t)) / peak(t)
    where peak(t) = max(price[0:t]).
    """

    def __init__(self) -> None:
        self._store = ParquetStore()

    def compute(self, ticker: str) -> dict[str, Any]:
        """Compute drawdown metrics for a ticker.

        Args:
            ticker: Stock ticker symbol.

        Returns:
            Dictionary of drawdown metrics.
        """
        df = self._store.read_daily(ticker)
        if df is None or len(df) < 30:
            return {"error": f"Insufficient data for {ticker}"}

        col = "adj_close" if "adj_close" in df.columns else "close"
        prices = df[col].values

        result = self.compute_from_prices(prices, list(df.index))
        result["ticker"] = ticker
        return result

    def compute_from_prices(
        self,
        prices: np.ndarray,
        dates: list | None = None,
    ) -> dict[str, Any]:
        """Compute drawdown from a price array.

        Args:
            prices: Array of prices.
            dates: Optional date labels.

        Returns:
            Drawdown metrics dictionary.
        """
        prices = np.asarray(prices, dtype=float)

        # Rolling max (peak)
        peak = np.maximum.accumulate(prices)

        # Drawdown series
        drawdown = (prices - peak) / np.maximum(peak, 1e-10)

        # Maximum drawdown
        max_dd = float(drawdown.min())
        max_dd_idx = int(np.argmin(drawdown))

        # Drawdown start (when peak was last set)
        peak_idx = int(np.argmax(np.where(peak == peak[max_dd_idx], range(len(peak)), 0)))

        # Drawdown duration
        dd_start = peak_idx
        dd_end = max_dd_idx

        # Recovery analysis
        recovery_idx = None
        for i in range(max_dd_idx, len(prices)):
            if prices[i] >= peak[max_dd_idx]:
                recovery_idx = i
                break

        dd_duration = dd_end - dd_start
        recovery_duration = (recovery_idx - dd_end) if recovery_idx is not None else None

        # Current drawdown
        current_dd = float(drawdown[-1])

        # Underwater curve
        underwater = drawdown[drawdown < 0]

        # Rolling max drawdown (252-day)
        roll_max_peak = pd.Series(prices).rolling(252, min_periods=1).max().values
        roll_dd = (prices - roll_max_peak) / np.maximum(roll_max_peak, 1e-10)
        roll_max_dd = float(np.min(roll_dd[-252:])) if len(roll_dd) >= 252 else max_dd

        # Average drawdown
        avg_dd = float(underwater.mean()) if len(underwater) > 0 else 0.0

        # Time underwater (consecutive days below peak)
        time_underwater = int(np.sum(drawdown < -0.001))

        result: dict[str, Any] = {
            "max_drawdown": round(max_dd, 6),
            "max_drawdown_pct": round(max_dd * 100, 2),
            "current_drawdown": round(current_dd, 6),
            "current_drawdown_pct": round(current_dd * 100, 2),
            "avg_drawdown": round(avg_dd, 6),
            "rolling_252d_max_dd": round(roll_max_dd, 6),
            "dd_start_idx": dd_start,
            "dd_end_idx": dd_end,
            "dd_duration_trading_days": dd_duration,
            "recovery_days": recovery_duration,
            "fully_recovered": recovery_idx is not None,
            "time_underwater_days": time_underwater,
            "n_obs": len(prices),
        }

        if dates:
            result["dd_start_date"] = str(dates[dd_start])[:10] if dd_start < len(dates) else ""
            result["dd_end_date"] = str(dates[dd_end])[:10] if dd_end < len(dates) else ""
            if recovery_idx is not None and recovery_idx < len(dates):
                result["recovery_date"] = str(dates[recovery_idx])[:10]

        return result

    def compute_rolling_drawdown(
        self,
        prices: np.ndarray,
        window: int = 252,
    ) -> np.ndarray:
        """Compute rolling maximum drawdown.

        Args:
            prices: Price array.
            window: Rolling window size.

        Returns:
            Array of rolling max drawdown values.
        """
        n = len(prices)
        result = np.zeros(n)
        for i in range(window, n + 1):
            segment = prices[i - window:i]
            peak = np.maximum.accumulate(segment)
            dd = (segment - peak) / np.maximum(peak, 1e-10)
            result[i - 1] = float(np.min(dd))
        return result
