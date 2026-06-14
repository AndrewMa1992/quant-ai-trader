"""services/execution_service/backtest/broker.py – Simulation broker.

Matching engine: market/limit orders, slippage, commission,
position tracking, cash management.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger

from services.execution_service.backtest.events import FillEvent, OrderEvent
from services.execution_service.backtest.slippage import SlippageModel
from services.execution_service.config import exec_config


class SimulationBroker:
    """Simulated broker with matching engine.

    Processes OrderEvents and produces FillEvents with:
    - Transaction costs (commission)
    - Slippage (fixed bp + Almgren-Chriss)
    - Position limits
    - Cash management
    """

    def __init__(
        self,
        initial_cash: float = 1_000_000.0,
        commission_bps: float | None = None,
        slippage_bps: float | None = None,
    ) -> None:
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.positions: dict[str, int] = {}
        self.cost_basis: dict[str, float] = {}
        self.commission_bps = commission_bps or exec_config.BACKTEST_COMMISSION_BPS
        self.slippage_model = SlippageModel(base_slippage_bps=slippage_bps or exec_config.BACKTEST_SLIPPAGE_BPS)
        self._fills: list[FillEvent] = []
        self._orders: list[OrderEvent] = []

    def execute_order(
        self,
        order: OrderEvent,
        current_price: float,
        volume: int = 0,
        timestamp: datetime | None = None,
    ) -> FillEvent | None:
        """Execute an order against the market.

        Args:
            order: Order to execute.
            current_price: Current market price.
            volume: Current market volume.
            timestamp: Execution timestamp.

        Returns:
            FillEvent or None if order cannot be filled.
        """
        if order.quantity <= 0:
            return None

        # Check cash
        estimated_cost = order.quantity * current_price
        if order.side == "BUY" and estimated_cost > self.cash * 1.1:
            logger.warning(f"Insufficient cash: {self.cash:.0f} < {estimated_cost:.0f}")
            return None

        # Apply slippage
        fill_price = self.slippage_model.apply(
            price=current_price,
            side=order.side,
            quantity=order.quantity,
            volume=volume,
        )

        # Limit order check
        if order.order_type == "LMT" and order.limit_price:
            if order.side == "BUY" and fill_price > order.limit_price:
                return None
            if order.side == "SELL" and fill_price < order.limit_price:
                return None

        # Commission
        commission = fill_price * order.quantity * self.commission_bps / 10000

        # Update positions
        if order.side == "BUY":
            self.cash -= fill_price * order.quantity + commission
            self.positions[order.ticker] = self.positions.get(order.ticker, 0) + order.quantity

            if order.ticker in self.cost_basis:
                total_qty = self.positions[order.ticker]
                old_cost = self.cost_basis[order.ticker]
                self.cost_basis[order.ticker] = (
                    (old_cost * (total_qty - order.quantity) + fill_price * order.quantity) / total_qty
                )
            else:
                self.cost_basis[order.ticker] = fill_price
        else:
            self.cash += fill_price * order.quantity - commission
            self.positions[order.ticker] = self.positions.get(order.ticker, 0) - order.quantity
            if self.positions[order.ticker] <= 0:
                self.positions.pop(order.ticker, None)
                self.cost_basis.pop(order.ticker, None)

        fill = FillEvent(
            ticker=order.ticker,
            side=order.side,
            quantity=order.quantity,
            price=fill_price,
            commission=commission,
            order_id=order.order_id,
            timestamp=timestamp or datetime.now(),
        )

        self._fills.append(fill)
        self._orders.append(order)

        return fill

    def get_total_value(self, prices: dict[str, float]) -> float:
        """Compute total portfolio value.

        Args:
            prices: Dict of ticker → current price.

        Returns:
            Total portfolio value.
        """
        position_value = sum(
            qty * prices.get(ticker, 0)
            for ticker, qty in self.positions.items()
        )
        return self.cash + position_value

    def get_pnl(self, prices: dict[str, float]) -> float:
        """Get unrealized P&L.

        Args:
            prices: Current prices.

        Returns:
            Unrealized P&L.
        """
        pnl = 0.0
        for ticker, qty in self.positions.items():
            if ticker in self.cost_basis:
                pnl += qty * (prices.get(ticker, 0) - self.cost_basis[ticker])
        return pnl

    def get_positions_summary(self, prices: dict[str, float]) -> list[dict[str, Any]]:
        """Get detailed position summary.

        Args:
            prices: Current prices.

        Returns:
            List of position dicts.
        """
        result = []
        for ticker, qty in self.positions.items():
            current_price = prices.get(ticker, 0)
            cost = self.cost_basis.get(ticker, 0)
            market_val = qty * current_price
            pnl = qty * (current_price - cost)
            result.append({
                "ticker": ticker,
                "quantity": qty,
                "cost_basis": round(cost, 2),
                "current_price": round(current_price, 2),
                "market_value": round(market_val, 2),
                "unrealized_pnl": round(pnl, 2),
                "pnl_pct": round(pnl / (abs(cost * qty) + 1e-10) * 100, 2),
            })
        return result
