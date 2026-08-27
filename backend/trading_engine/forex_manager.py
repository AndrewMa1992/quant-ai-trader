"""
Forex Manager — automatic multi-currency FX.

Auto-converts across USD/HKD/SGD so each market has enough cash to trade.
Uses Tiger API currency_exchange when available, otherwise logs for manual action.

P2: universe scan + auto FX + lot prediction + capital filter
"""
from __future__ import annotations

from typing import Dict, Optional, List
from dataclasses import dataclass, field

from loguru import logger
from configs.settings import settings


# Supported currencies
SUPPORTED_CURRENCIES = ["USD", "HKD", "SGD"]

# Minimum FX amount (USD equivalent)
MIN_FOREX_AMOUNT_USD = 10.0

# Per-market cash buffer (local currency)
MARKET_BUFFER = {
    "USD": 50.0,
    "HKD": 500.0,   # ~$64 USD
    "SGD": 100.0,   # ~$75 USD
}


@dataclass
class ForexOrder:
    """FX order."""
    from_currency: str
    to_currency: str
    amount: float  # Quantity in from_currency
    amount_usd: float  # USD equivalent
    rate: float  # from→to FX rate
    reason: str

    def __repr__(self):
        return (f"Forex: {self.from_currency} {self.amount:.2f} → "
                f"{self.to_currency} ({self.amount_usd:.2f} USD) [{self.reason}]")


class ForexManager:
    """
    Automatic FX manager.

    Logic:
    1. Before each trading round, estimate per-market cash demand
    2. If a market is short cash, convert from a surplus market
    3. Execute via Tiger API when supported, otherwise raise an alert
    """

    def __init__(self, tiger_client=None):
        self._tiger = tiger_client
        self._pending_orders: List[ForexOrder] = []
        self._executed_orders: List[ForexOrder] = []
        self._last_forex_time: float = 0
        self._min_interval = 300  # Minimum FX interval: 5 minutes

    # ── Core: evaluate FX demand ──
    def evaluate(
        self,
        account_segments: Dict[str, Dict],
        target_trades: List[Dict],
    ) -> List[ForexOrder]:
        """
        Evaluate FX demand from account segments and pending trades.

        Args:
            account_segments: Return value of Tiger get_account_segments()
                {"US": {"cash": ..., "market_value": ...}, "HK": {...}, ...}
            target_trades: Pending trades
                [{"ticker": "AAPL", "side": "buy", "value": 500, "currency": "USD"}, ...]

        Returns:
            FX orders (priority-sorted)
        """
        import time
        now = time.time()
        if now - self._last_forex_time < self._min_interval:
            return []  # Cooldown

        # 1. Available cash per market (USD equivalent)
        cash_usd = {}
        for ccy in SUPPORTED_CURRENCIES:
            rate = settings.trading_currency_rates_dict.get(ccy, 1.0)
            seg = account_segments.get(ccy, {})
            local_cash = seg.get("cash", 0)
            cash_usd[ccy] = local_cash * rate

        total_usd = sum(cash_usd.values())
        if total_usd < 100:
            return []  # Too little capital to FX

        # 2. Trade demand per market (USD equivalent)
        demand_usd = {"USD": 0.0, "HKD": 0.0, "SGD": 0.0}
        for trade in target_trades:
            if trade.get("side") != "buy":
                continue
            ccy = trade.get("currency", "USD")
            value_usd = trade.get("value", 0) * settings.trading_currency_rates_dict.get(ccy, 1.0)
            demand_usd[ccy] += value_usd

        # 3. Detect gaps — which markets are short cash
        orders = []
        for ccy in ["HKD", "SGD", "USD"]:
            available = cash_usd.get(ccy, 0)
            buffer = MARKET_BUFFER.get(ccy, 50) * settings.trading_currency_rates_dict.get(ccy, 1.0)
            needed = demand_usd.get(ccy, 0) + buffer

            if needed > available:
                deficit = needed - available
                # Find a market with surplus cash
                for src_ccy in ["USD", "HKD", "SGD"]:
                    if src_ccy == ccy:
                        continue
                    src_available = cash_usd.get(src_ccy, 0)
                    src_demand = demand_usd.get(src_ccy, 0)
                    src_buffer = MARKET_BUFFER.get(src_ccy, 50) * settings.trading_currency_rates_dict.get(src_ccy, 1.0)
                    src_surplus = src_available - src_demand - src_buffer

                    if src_surplus > MIN_FOREX_AMOUNT_USD and deficit > MIN_FOREX_AMOUNT_USD:
                        amount_usd = min(deficit, src_surplus)
                        # Convert back to source-currency quantity
                        src_rate = settings.trading_currency_rates_dict.get(src_ccy, 1.0)
                        amount_from = amount_usd / src_rate
                        # Rate: from→to
                        to_rate = settings.trading_currency_rates_dict.get(ccy, 1.0)
                        exchange_rate = src_rate / to_rate

                        order = ForexOrder(
                            from_currency=src_ccy,
                            to_currency=ccy,
                            amount=round(amount_from, 2),
                            amount_usd=round(amount_usd, 2),
                            rate=round(exchange_rate, 4),
                            reason=f"Cash gap: {ccy} needs {needed:.0f}, short {deficit:.0f} USD",
                        )
                        orders.append(order)
                        cash_usd[src_ccy] -= amount_usd
                        cash_usd[ccy] += amount_usd
                        break

        return orders

    # ── Execute FX ──
    def execute(self, orders: List[ForexOrder]) -> List[Dict]:
        """
        Execute FX orders.

        Tiger API may not support direct FX — log and return status if it cannot run.
        """
        results = []
        import time

        for order in orders:
            logger.info(f"💱 {order}")
            result = {
                "from": order.from_currency,
                "to": order.to_currency,
                "amount": order.amount,
                "amount_usd": order.amount_usd,
                "rate": order.rate,
                "status": "pending",
                "message": "",
            }

            # Try Tiger API FX
            if self._tiger and self._tiger.is_connected():
                try:
                    # Tiger SDK: try currency_exchange
                    trade_client = self._tiger._trade_client
                    if hasattr(trade_client, 'forex_exchange'):
                        fx_result = trade_client.forex_exchange(
                            from_currency=order.from_currency,
                            to_currency=order.to_currency,
                            amount=order.amount,
                        )
                        result["status"] = "executed"
                        result["order_id"] = getattr(fx_result, 'id', '')
                        result["message"] = f"Tiger FX succeeded"
                        logger.info(f"  ✅ FX executed: {result['message']}")
                    else:
                        result["status"] = "alert"
                        result["message"] = "Tiger API does not support auto FX — logged for manual action"
                        logger.warning(f"  ⚠️ {result['message']}")
                except Exception as e:
                    result["status"] = "failed"
                    result["message"] = f"FX failed: {e}"
                    logger.error(f"  ❌ {result['message']}")
            else:
                result["status"] = "offline"
                result["message"] = "Tiger not connected — log only"
                logger.info(f"  📝 {result['message']}")

            results.append(result)
            self._pending_orders.append(order)

        self._last_forex_time = time.time()
        return results

    # ── Auto FX (one-shot) ──
    def auto_forex(
        self,
        account_segments: Dict[str, Dict],
        target_trades: List[Dict],
    ) -> Dict:
        """
        Auto-FX entry: evaluate → execute → return results.

        Returns:
            {
                "orders": [...],        # FX orders
                "results": [...],       # Execution results
                "total_converted_usd": 0,  # Total FX notional in USD
            }
        """
        orders = self.evaluate(account_segments, target_trades)

        if not orders:
            return {"orders": [], "results": [], "total_converted_usd": 0}

        total_usd = sum(o.amount_usd for o in orders)
        logger.info(f"💱 Auto FX: {len(orders)} orders, total ${total_usd:,.2f} USD")

        results = self.execute(orders)
        return {
            "orders": [{
                "from": o.from_currency,
                "to": o.to_currency,
                "amount": o.amount,
                "amount_usd": o.amount_usd,
                "reason": o.reason,
            } for o in orders],
            "results": results,
            "total_converted_usd": total_usd,
        }

    # ── FX rate lookup ──
    @staticmethod
    def get_fx_rate(from_ccy: str, to_ccy: str) -> float:
        """Return the FX rate between two currencies."""
        from_rate = settings.trading_currency_rates_dict.get(from_ccy, 1.0)
        to_rate = settings.trading_currency_rates_dict.get(to_ccy, 1.0)
        return from_rate / to_rate

    # ── Helper: local-currency trade value ──
    @staticmethod
    def calc_trade_local_value(
        ticker: str,
        quantity: float,
        price: float,
    ) -> dict:
        """Compute a trade's local-currency value and USD equivalent."""
        from backend.trading_engine.portfolio import PortfolioManager

        pm = PortfolioManager.__new__(PortfolioManager)
        currency = pm._get_currency(ticker) if hasattr(pm, '_get_currency') else "USD"

        local_value = quantity * price
        usd_value = local_value * settings.trading_currency_rates_dict.get(currency, 1.0)

        return {
            "currency": currency,
            "local_value": round(local_value, 2),
            "usd_value": round(usd_value, 2),
        }

    # ── Summary ──
    def get_status(self) -> Dict:
        return {
            "pending_orders": len(self._pending_orders),
            "executed_orders": len(self._executed_orders),
            "total_converted": sum(o.amount_usd for o in self._executed_orders),
            "last_forex_time": self._last_forex_time,
        }


# Global singleton
forex_manager = ForexManager()
