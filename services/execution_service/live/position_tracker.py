"""services/execution_service/live/position_tracker.py – Real-time position tracker.

Tracks: P&L, cost basis, unrealized gains, intraday trade counts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class PositionTracker:
    """Tracks portfolio positions and computes P&L in real time.

    Tracks:
    - Current positions with cost basis
    - Realized and unrealized P&L
    - Intraday trade counts (for PDT checks)
    - Position-level risk metrics
    """

    def __init__(self) -> None:
        self.positions: dict[str, dict[str, Any]] = {}
        self._trade_log: list[dict[str, Any]] = []
        self._intraday_trades: dict[str, int] = {}
        self._realized_pnl: float = 0.0

    def record_order(self, order_result: dict[str, Any]) -> None:
        """Record an executed order.

        Args:
            order_result: Order confirmation from broker.
        """
        ticker = order_result.get("ticker", "")
        side = order_result.get("side", "")
        quantity = order_result.get("quantity", 0)
        status = order_result.get("status", "")

        if "SUBMITTED" not in status and "FILLED" not in status:
            return

        if ticker not in self.positions:
            self.positions[ticker] = {
                "quantity": 0,
                "cost_basis": 0.0,
                "market_value": 0.0,
                "unrealized_pnl": 0.0,
                "day_trades": 0,
            }

        pos = self.positions[ticker]
        qty = int(quantity)

        if side == "BUY":
            if pos["quantity"] < 0:
                # Close short
                cover_qty = min(qty, -pos["quantity"])
                self._realized_pnl += cover_qty * (pos["cost_basis"] - float(order_result.get("price", 0)))
                qty -= cover_qty
                pos["quantity"] += cover_qty

            if qty > 0:
                # Add long
                new_total = pos["quantity"] + qty
                old_cost = pos["cost_basis"] * pos["quantity"]
                new_cost = qty * float(order_result.get("price", 0))
                pos["quantity"] = new_total
                pos["cost_basis"] = (old_cost + new_cost) / max(new_total, 1)

        elif side == "SELL":
            if pos["quantity"] > 0:
                # Sell long
                sell_qty = min(qty, pos["quantity"])
                self._realized_pnl += sell_qty * (float(order_result.get("price", 0)) - pos["cost_basis"])
                pos["quantity"] -= sell_qty

            if pos["quantity"] == 0:
                pos["cost_basis"] = 0.0

        # Track intraday
        self._intraday_trades[ticker] = self._intraday_trades.get(ticker, 0) + 1
        pos["day_trades"] = self._intraday_trades[ticker]

        self._trade_log.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ticker": ticker,
            "side": side,
            "quantity": quantity,
            "status": status,
        })

    def update_market_prices(self, prices: dict[str, float]) -> None:
        """Update positions with latest market prices.

        Args:
            prices: Dict of ticker → current price.
        """
        for ticker, pos in self.positions.items():
            if ticker in prices and pos["quantity"] != 0:
                current_price = prices[ticker]
                pos["market_value"] = pos["quantity"] * current_price
                pos["unrealized_pnl"] = pos["quantity"] * (current_price - pos["cost_basis"])

    def get_positions(self) -> list[dict[str, Any]]:
        """Get all current positions.

        Returns:
            List of position dicts.
        """
        return [
            {
                "ticker": t,
                "quantity": p["quantity"],
                "cost_basis": round(p["cost_basis"], 2),
                "market_value": round(p["market_value"], 2),
                "unrealized_pnl": round(p["unrealized_pnl"], 2),
                "day_trades": p["day_trades"],
            }
            for t, p in self.positions.items()
            if p["quantity"] != 0
        ]

    def get_summary(self) -> dict[str, Any]:
        """Get portfolio summary.

        Returns:
            Portfolio-level metrics.
        """
        total_market_value = sum(p["market_value"] for p in self.positions.values())
        total_unrealized = sum(p["unrealized_pnl"] for p in self.positions.values())
        position_count = sum(1 for p in self.positions.values() if p["quantity"] != 0)

        return {
            "position_count": position_count,
            "total_market_value": round(total_market_value, 2),
            "unrealized_pnl": round(total_unrealized, 2),
            "realized_pnl": round(self._realized_pnl, 2),
            "total_pnl": round(total_unrealized + self._realized_pnl, 2),
            "intraday_trades": sum(self._intraday_trades.values()),
        }

    def get_trade_log(self, max_count: int = 100) -> list[dict[str, Any]]:
        """Get recent trades.

        Args:
            max_count: Max entries.

        Returns:
            Recent trade list.
        """
        return self._trade_log[-max_count:]
