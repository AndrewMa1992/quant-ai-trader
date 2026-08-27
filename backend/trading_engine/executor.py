"""
Order executor.
- Live: place orders via the Tiger Brokers API
- Pre-trade risk checks
- Persist trade records
"""
from typing import Dict, List, Optional, Callable
from loguru import logger

from configs.settings import settings
from backend.trading_engine.risk_manager import RiskManager
from backend.trading_engine.portfolio import PortfolioManager
from backend.data_engine.tiger_client import tiger_client, TigerClient


class PaperExecutor:
    """
    Order executor.
    - Place live orders when tiger_client is connected
    - Otherwise degrade to paper trading
    """

    def __init__(self, portfolio: PortfolioManager, risk_manager: RiskManager):
        self.portfolio = portfolio
        self.risk_manager = risk_manager
        self._order_callbacks: List[Callable] = []
        self.pending_orders: List[Dict] = []
        self.filled_orders: List[Dict] = []
        # Whether to place live Tiger orders (checked dynamically in execute_signal)
        self._tiger_account = settings.TIGER_ACCOUNT
        if self._tiger_account:
            logger.info(f"📝 Tiger live account: {self._tiger_account}")
        else:
            logger.warning("⚠️ Tiger account not configured; live trading unavailable")

    # ================================================================
    # Order execution
    # ================================================================

    def execute_signal(
        self,
        ticker: str,
        decision: str,
        strength: float,
        price: float,
        confidence: float = 0.5,
        strategy: str = "ensemble",
    ) -> Optional[Dict]:
        """
        Execute a trade from a signal.

        Args:
            ticker: Symbol
            decision: buy / sell / hold
            strength: Signal strength 0~1
            price: Current price
            confidence: Confidence 0~1
            strategy: Strategy name

        Returns:
            trade_record or None
        """
        # Hold signals are not executed
        if decision == "hold":
            return None

        side = decision  # buy or sell

        # No leverage — two-layer verification
        if settings.TRADING_NO_LEVERAGE and side == "buy":
            # Layer 1: local cash check
            max_buy_value = self.portfolio.cash * settings.TRADING_MAX_CASH_USAGE
            estimated_value = self.portfolio.cash * min(strength, settings.TRADING_MAX_POSITION_SIZE)
            if estimated_value > max_buy_value:
                logger.warning(
                    f"🚫 No-leverage reject (local): {ticker} buy | "
                    f"est. ${estimated_value:,.0f} > available ${max_buy_value:,.0f}"
                )
                return None
            
            # Layer 2: Tiger live cash check — ensure the Tiger account is also unlevered
            if self._tiger_account and tiger_client.is_connected():
                try:
                    tiger_acct = tiger_client.get_account_info()
                    if tiger_acct:
                        tiger_cash = tiger_acct.get("cash", 0)
                        tiger_total = tiger_acct.get("total_value", 0)
                        tiger_leverage = tiger_acct.get("leverage", 1.0)
                        tiger_mkt = tiger_acct.get("market_value", 0)
                        
                        # Leverage probe: leverage > 1.001 means borrowed funds
                        if tiger_leverage > 1.001:
                            logger.warning(
                                f"🚫 No-leverage reject (Tiger): {ticker} buy | "
                                f"Tiger leverage {tiger_leverage:.4f} > 1.0 | "
                                f"Clear leverage before buying"
                            )
                            return None
                        
                        # Buy notional must not exceed Tiger cash
                        if estimated_value > tiger_cash * settings.TRADING_MAX_CASH_USAGE:
                            logger.warning(
                                f"🚫 No-leverage reject (Tiger): {ticker} buy | "
                                f"est. ${estimated_value:,.0f} > Tiger cash ${tiger_cash:,.0f}×{settings.TRADING_MAX_CASH_USAGE:.0%}"
                            )
                            return None
                except Exception as e:
                    logger.warning(f"⚠️ Tiger leverage check failed; using conservative local policy: {e}")

        # Confidence threshold
        if confidence < settings.TRADING_MIN_CONFIDENCE:
            return None

        # 1. Risk check
        if side == "buy":
            buy_strength = min(strength, settings.TRADING_MAX_POSITION_SIZE)
            estimated_value = self.portfolio.cash * buy_strength
            quantity = estimated_value / price if price > 0 else 0
            if quantity < settings.TRADING_MIN_SHARES:
                return None
        else:
            shares = self.portfolio.positions.get(ticker, 0.0)
            if shares < settings.TRADING_MIN_SHARES:
                return None  # No position to sell
            quantity = shares * strength
            if quantity < settings.TRADING_MIN_SHARES:
                quantity = shares  # Sell all if below the minimum size
            
            # Prevent shorts: cap sell qty to Tiger's actual position
            if self._tiger_account and tiger_client.is_connected():
                try:
                    tiger_positions = tiger_client.get_positions()
                    tiger_dict = {p["ticker"]: p for p in tiger_positions}
                    if ticker in tiger_dict:
                        tiger_shares = tiger_dict[ticker]["shares"]
                        if tiger_shares <= 0:
                            logger.warning(
                                f"🚫 Reject sell: {ticker} | Tiger position {tiger_shares:.2f} ≤ 0, "
                                f"local thought it held {shares:.2f} shares — data out of sync"
                            )
                            return None
                        if quantity > tiger_shares:
                            old_qty = quantity
                            quantity = tiger_shares
                            logger.warning(
                                f"⚠️ Sell qty adjusted: {ticker} | "
                                f"local {shares:.2f} sh → Tiger actual {tiger_shares:.2f} sh | "
                                f"sell {old_qty:.0f} → {quantity:.0f}"
                            )
                    else:
                        # Ticker not in Tiger positions
                        logger.warning(
                            f"🚫 Reject sell: {ticker} | "
                            f"local holds {shares:.2f} shares but Tiger has none — data out of sync"
                        )
                        return None
                except Exception as e:
                    logger.warning(f"⚠️ Tiger position verification failed: {e}")

        # Minimum notional check
        if quantity * price < settings.TRADING_MIN_TRADE_VALUE:
            return None

        # HK/SG buys: round to board lots (sells are not lot-constrained)
        is_hk = ticker.endswith(".HK") or (len(ticker) <= 5 and ticker.isdigit())
        is_sg = ticker.endswith(".SI")
        if side == "buy" and (is_hk or is_sg):
            lot = TigerClient.get_hk_lot_size(ticker)
            proposed_qty = int(quantity)

            # Below one lot: try buying exactly 1 lot (without exceeding position cap)
            if proposed_qty < lot:
                min_qty = lot
                min_value = min_qty * price
                max_allowed = self.portfolio.cash * settings.TRADING_MAX_CASH_USAGE
                if min_value <= max_allowed and min_value >= settings.TRADING_MIN_TRADE_VALUE:
                    quantity = float(min_qty)
                    logger.info(f"📐 {ticker} stepped up to 1 lot: {proposed_qty} → {min_qty} sh (${min_value:.0f})")
                else:
                    logger.debug(f"⏸ {ticker} below 1 lot (lot={lot}, need=${min_value:.0f}, avail=${max_allowed:.0f}), skip")
                    return None
            else:
                # Round down to a whole lot
                round_qty = (proposed_qty // lot) * lot
                if round_qty < lot:
                    logger.debug(f"⏸ {ticker} below 1 lot after rounding (lot={lot}), skip")
                    return None
                if round_qty != proposed_qty:
                    logger.info(f"📐 {ticker} lot-aligned: {proposed_qty} → {round_qty} sh")
                    quantity = float(round_qty)
                # Re-check notional after lot alignment
                if quantity * price < settings.TRADING_MIN_TRADE_VALUE:
                    logger.debug(f"⏸ {ticker} notional too small after lot alignment: ${quantity * price:.0f}")
                    return None

        report = self.risk_manager.check_order(ticker, side, quantity, price)

        if not report.passed:
            logger.warning(f"🔴 Risk rejected: {ticker} {side} | {report.violations}")
            return None

        # 2. Execute
        # Prefer local simulated fill so trading logic always runs
        trade = self.portfolio.execute_trade(
            ticker=ticker,
            side=side,
            price=price,
            signal_strength=strength,
            strategy=strategy,
        )
        
        if trade:
            self.filled_orders.append(trade)
            self._emit_order_filled(trade)
            
            # Also send to Tiger live if configured and connected
            use_tiger_now = bool(self._tiger_account and tiger_client.is_connected())
            if use_tiger_now:
                try:
                    action = "BUY" if side == "buy" else "SELL"
                    order_result = tiger_client.place_order(
                        ticker=ticker,
                        action=action,
                        quantity=int(quantity),
                        order_type="MKT",
                        limit_price=price,
                    )
                    if order_result:
                        logger.info(f"✅ Live order placed: {ticker} {action} | order id: {order_result.get('order_id')}")
                    else:
                        logger.warning(f"⚠️ Live order returned empty: {ticker} {action}")
                except Exception as e:
                    logger.error(f"❌ Tiger order error: {ticker} {action} | {e}")
            
            return trade
        
        return None

    def execute_signal_batch(
        self,
        signals: Dict[str, Dict],
        prices: Dict[str, float],
    ) -> List[Dict]:
        """
        Execute a batch of signals.

        Args:
            signals: {ticker: {decision, strength, confidence}}
            prices: {ticker: price}

        Returns:
            Fill records
        """
        trades = []

        # Sort by signal strength; execute high-confidence names first
        sorted_signals = sorted(
            signals.items(),
            key=lambda x: (x[1].get("confidence") or 0) * abs(x[1].get("strength") or 0),
            reverse=True,
        )

        for ticker, signal in sorted_signals:
            price = prices.get(ticker)
            if price is None or price <= 0:
                continue

            trade = self.execute_signal(
                ticker=ticker,
                decision=signal.get("decision") or "hold",
                strength=signal.get("strength") or 0.0,
                price=price,
                confidence=signal.get("confidence") or 0.5,
            )

            if trade:
                trades.append(trade)

        return trades

    # ================================================================
    # Callbacks
    # ================================================================

    def on_order_filled(self, callback: Callable):
        """Register a fill callback."""
        self._order_callbacks.append(callback)

    def _emit_order_filled(self, trade: Dict):
        """Fire fill callbacks."""
        for cb in self._order_callbacks:
            try:
                cb(trade)
            except Exception as e:
                logger.error(f"❌ Callback error: {e}")

    # ================================================================
    # Tiger Brokers adapter (reserved)
    # ================================================================

    def _tiger_place_order(self, ticker: str, side: str, quantity: float, price: float):
        """
        Place a Tiger Brokers order (reserved).
        Enable when switching to live trading.
        """
        # from tiger_open_python_sdk import TigerApiClient
        # client = TigerApiClient(settings.TIGER_ID, ...)
        # order = client.place_order(
        #     account=settings.TIGER_ACCOUNT,
        #     symbol=ticker,
        #     action="BUY" if side == "buy" else "SELL",
        #     quantity=int(quantity),
        #     order_type="LMT" if price else "MKT",
        #     limit_price=price,
        # )
        raise NotImplementedError("Tiger Brokers live trading is not wired yet")

    def get_execution_summary(self) -> Dict:
        """Return an execution summary."""
        return {
            "total_filled": len(self.filled_orders),
            "total_pending": len(self.pending_orders),
            "buy_count": len([t for t in self.filled_orders if t["side"] == "buy"]),
            "sell_count": len([t for t in self.filled_orders if t["side"] == "sell"]),
        }
