"""services/execution_service/backtest/slippage.py – Slippage models.

- Fixed bp: constant basis point cost
- Almgren-Chriss: L1 (bid-ask) + L2 (volume impact)
"""

from __future__ import annotations

import numpy as np


class SlippageModel:
    """Slippage model for transaction cost estimation.

    Total slippage = fixed_bps + Almgren-Chriss impact.

    Attributes:
        base_slippage_bps: Fixed transaction cost in basis points.
        impact_factor: Almgren-Chriss impact coefficient (η).
        use_volume_impact: Whether to include volume-dependent slippage.
    """

    def __init__(
        self,
        base_slippage_bps: float = 2.0,
        impact_factor: float = 0.1,
        use_volume_impact: bool = True,
    ) -> None:
        self.base_slippage_bps = base_slippage_bps
        self.impact_factor = impact_factor
        self.use_volume_impact = use_volume_impact

    def apply(
        self,
        price: float,
        side: str,
        quantity: int,
        volume: int = 0,
    ) -> float:
        """Compute fill price with slippage.

        Args:
            price: Mid/market price.
            side: 'BUY' or 'SELL'.
            quantity: Order quantity.
            volume: Current market volume (0 = no volume impact).

        Returns:
            Fill price after slippage.
        """
        if quantity <= 0:
            return price

        # Fixed cost in bps
        fixed_cost = price * self.base_slippage_bps / 10000

        # Almgren-Chriss L2 impact
        volume_impact = 0.0
        if self.use_volume_impact and volume > 0 and quantity > 0:
            participation_rate = quantity / max(volume, 1)
            # Square-root impact model: σ * (Q / V)^β
            sigma = 0.2 / np.sqrt(252)  # Approx daily vol
            volume_impact = price * self.impact_factor * sigma * (participation_rate ** 0.5)

        total_slippage = fixed_cost + volume_impact

        if side.upper() == "BUY":
            return price + total_slippage
        else:
            return price - total_slippage

    def estimate_cost(
        self,
        price: float,
        side: str,
        quantity: int,
        volume: int = 0,
    ) -> dict[str, float]:
        """Estimate transaction cost components.

        Args:
            price: Current price.
            side: Order side.
            quantity: Order quantity.
            volume: Market volume.

        Returns:
            Dict with cost breakdown.
        """
        fixed_cost = price * self.base_slippage_bps / 10000

        volume_impact = 0.0
        if self.use_volume_impact and volume > 0:
            participation = quantity / max(volume, 1)
            sigma = 0.2 / np.sqrt(252)
            volume_impact = price * self.impact_factor * sigma * (participation ** 0.5)

        return {
            "fixed_cost": round(fixed_cost, 4),
            "volume_impact": round(volume_impact, 4),
            "total_slippage": round(fixed_cost + volume_impact, 4),
            "total_bps": round((fixed_cost + volume_impact) / price * 10000, 2),
            "participation_rate": round(quantity / max(volume, 1), 4) if volume > 0 else 0.0,
        }
