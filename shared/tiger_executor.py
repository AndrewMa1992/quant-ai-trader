"""
TigerExecutor — unified live / paper execution engine
======================================================
Replaces ``backend.trading_engine.executor.PaperExecutor``.
Zero ``import backend.`` — depends on ``shared.portfolio_manager``,
``shared.risk_manager``, and ``shared.tiger_bridge``.

Strategy pattern: ``mode="live"`` → real Tiger orders;
``mode="paper"`` → local portfolio updates only.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loguru import logger


# ── Lot-size helpers (no backend dependency) ──────────────────

# Common HK lot sizes indexed by ticker root.  Default = 100.
_HK_LOT_MAP: Dict[str, int] = {
    "0700": 100,   # Tencent
    "9988": 100,   # Alibaba HK
    "9618": 50,    # JD HK
    "9999": 100,   # NetEase HK
    "1810": 200,   # Xiaomi
    "3690": 100,   # Meituan
    "2269": 100,   # WuXi Biologics
    "2318": 500,   # Ping An
    "0388": 100,   # HKEX
    "0005": 400,   # HSBC
    "0941": 500,   # China Mobile
    "3988": 1000,  # BOC
    "1398": 1000,  # ICBC
    "0939": 1000,  # CCB
    "2628": 1000,  # China Life
}

_DEFAULT_HK_LOT: int = 100
_DEFAULT_SG_LOT: int = 100


def _is_hk_ticker(ticker: str) -> bool:
    """Heuristic: is this a Hong Kong ticker?"""
    return ticker.endswith(".HK") or (len(ticker) <= 5 and ticker.isdigit())


def _is_sg_ticker(ticker: str) -> bool:
    """Heuristic: is this a Singapore ticker?"""
    return ticker.endswith(".SI")


def _get_lot_size(ticker: str) -> int:
    """Return the minimum lot size for a ticker.

    For HK stocks, looks up a known lot-size table; defaults to 100.
    For SG stocks, defaults to 100.
    """
    if _is_hk_ticker(ticker):
        root: str = ticker.replace(".HK", "").strip()
        return _HK_LOT_MAP.get(root, _DEFAULT_HK_LOT)
    if _is_sg_ticker(ticker):
        return _DEFAULT_SG_LOT
    return 1  # US stocks: no lot restriction


def _round_lot(ticker: str, quantity: float, side: str) -> float:
    """Round quantity to whole-lot for HK / SG buys.

    Args:
        ticker: Ticker symbol.
        quantity: Proposed share count.
        side: ``"buy"`` or ``"sell"``.

    Returns:
        Adjusted quantity. For non-HK/SG or sells, returns original.
    """
    lot: int = _get_lot_size(ticker)
    if lot <= 1:
        return quantity  # US stocks: no rounding
    if side.lower().strip() != "buy":
        return quantity  # Only restrict buys
    qty_int: int = int(quantity)
    rounded: int = (qty_int // lot) * lot
    if rounded < lot:
        return 0.0  # Not enough for one lot
    return float(rounded)


# ═══════════════════════════════════════════════════════════════


class TigerExecutor:
    """Unified order executor with live / paper strategy.

    Typical usage:

        >>> executor = TigerExecutor(
        ...     mode="paper",
        ...     portfolio=portfolio,
        ...     risk=risk_manager,
        ...     tiger_bridge=tiger_bridge,
        ... )
        >>> order = executor.execute_signal(
        ...     "AAPL", "BUY", 0.15, 180.0, 0.7, "ensemble"
        ... )
    """

    def __init__(
        self,
        mode: str,
        portfolio: Any,
        risk: Any,
        tiger_bridge: Any,
    ) -> None:
        """Initialise the executor.

        Args:
            mode: ``"live"`` or ``"paper"``.
            portfolio: ``shared.portfolio_manager.PortfolioManager`` instance.
            risk: ``shared.risk_manager.RiskManager`` instance.
            tiger_bridge: ``shared.tiger_bridge`` module reference.
        """
        if mode not in ("live", "paper"):
            raise ValueError(f"mode must be 'live' or 'paper', got {mode!r}")
        self.mode: str = mode
        self.portfolio = portfolio
        self.risk = risk
        self.tiger = tiger_bridge

        self.filled_orders: List[Dict[str, Any]] = []

        logger.info(
            f"TigerExecutor initialised | mode={mode} | "
            f"capital=${portfolio.initial_capital:,.0f}"
        )

    # ═══════════════════════════════════════════════════════════════
    # Public API
    # ═══════════════════════════════════════════════════════════════

    def execute_signal(
        self,
        ticker: str,
        decision: str,
        strength: float,
        price: float,
        confidence: float = 0.5,
        strategy: str = "ensemble",
    ) -> Optional[Dict[str, Any]]:
        """Execute a single trading signal.

        Args:
            ticker: Stock ticker.
            decision: ``"BUY"`` / ``"SELL"`` / ``"HOLD"`` (case-insensitive).
            strength: Signal strength 0.0–1.0.
            price: Current price (USD).
            confidence: Model confidence 0.0–1.0.
            strategy: Strategy label for record-keeping.

        Returns:
            Trade record dict, or None if the signal was rejected
            or resulted in no trade.
        """
        decision_upper: str = decision.upper().strip()

        # HOLD → no action.
        if decision_upper == "HOLD":
            return None

        if decision_upper not in ("BUY", "SELL"):
            logger.warning(f"TigerExecutor: invalid decision {decision!r} for {ticker}")
            return None

        if price <= 0.0 or strength <= 0.0 or confidence < 0.0:
            logger.debug(f"TigerExecutor: signal below threshold for {ticker}")
            return None

        # ── Calculate quantity ─────────────────────────────────
        quantity: float = self._calc_quantity(ticker, decision_upper, strength, price)
        if quantity <= 0.0:
            logger.debug(f"TigerExecutor: zero quantity for {ticker}")
            return None

        # ── HK / SG lot rounding (buys only) ───────────────────
        if decision_upper == "BUY":
            rounded: float = _round_lot(ticker, quantity, "buy")
            if rounded <= 0.0:
                logger.debug(
                    f"TigerExecutor: {ticker} lot rounding → 0 (lot={_get_lot_size(ticker)})"
                )
                return None
            if rounded != quantity:
                logger.info(f"📐 {ticker} 整手对齐: {int(quantity)} → {int(rounded)} 股")
                quantity = rounded

        # ── Risk check ─────────────────────────────────────────
        side_key: str = "buy" if decision_upper == "BUY" else "sell"
        risk_report = self.risk.check_order(ticker, side_key, quantity, price)
        if not risk_report.passed:
            logger.warning(
                f"🔴 风控拒绝: {ticker} {decision_upper} | {risk_report.reason}"
            )
            return {
                "ticker": ticker,
                "side": decision_upper.lower(),
                "quantity": round(quantity, 4),
                "price": round(price, 2),
                "rejected": True,
                "reason": risk_report.reason,
                "strategy": strategy,
                "timestamp": __import__("datetime").datetime.now().isoformat(),
            }

        # ── Execute ────────────────────────────────────────────
        if self.mode == "live":
            try:
                from shared.kill_switch import get_kill_switch
                from shared.live_promotion import can_place_live_orders

                if get_kill_switch().engaged:
                    logger.error(f"🛑 Kill switch blocks live order: {ticker}")
                    return {
                        "ticker": ticker,
                        "side": decision_upper.lower(),
                        "quantity": round(quantity, 4),
                        "price": round(price, 2),
                        "rejected": True,
                        "reason": "kill_switch_engaged",
                        "strategy": strategy,
                    }
                if not can_place_live_orders():
                    logger.warning(
                        f"Live promotion gate blocked {ticker} — forcing paper fill"
                    )
                    trade = self._execute_paper(
                        ticker, decision_upper, quantity, price, strategy
                    )
                    if trade:
                        trade["forced_paper"] = True
                        self._attach_tca(trade, arrival_price=price)
                        self.filled_orders.append(trade)
                        self.risk.record_trade()
                    return trade
            except Exception as gate_exc:
                logger.warning(f"Live gate check error: {gate_exc}")

            trade: Optional[Dict[str, Any]] = self._execute_live(
                ticker, decision_upper, quantity, price, strategy
            )
        else:
            trade = self._execute_paper(
                ticker, decision_upper, quantity, price, strategy
            )

        if trade:
            self._attach_tca(trade, arrival_price=price)
            self.filled_orders.append(trade)
            self.risk.record_trade()

        return trade

    def _attach_tca(self, trade: Dict[str, Any], arrival_price: float) -> None:
        """Record institutional-lite TCA on fills (non-blocking)."""
        if trade.get("rejected"):
            return
        try:
            from services.execution_service.live.tca import analyze_fill, to_dict
            from shared.audit_trail import get_audit_trail

            fill_px = float(trade.get("price") or arrival_price or 0.0)
            result = analyze_fill(
                ticker=str(trade.get("ticker", "")),
                side=str(trade.get("side", "buy")),
                quantity=float(trade.get("quantity") or 0.0),
                arrival_price=float(arrival_price or fill_px),
                fill_price=fill_px,
                adv_usd=None,
            )
            trade["tca"] = to_dict(result)
            get_audit_trail().write("tca", trade["tca"])
            if not result.passed:
                logger.warning(f"TCA flag {trade.get('ticker')}: {result.reason}")
        except Exception as exc:
            logger.debug(f"TCA attach skipped: {exc}")

    def execute_rebalance(
        self,
        target_weights: Dict[str, float],
        prices: Dict[str, float],
        current_positions: Optional[Dict[str, float]] = None,
    ) -> List[Dict[str, Any]]:
        """Execute a portfolio rebalance given target weights.

        For each ticker in ``target_weights``, computes the weight
        difference vs current positions and issues BUY / SELL signals.

        Args:
            target_weights: ticker → target weight (e.g. 0.05 = 5%).
            prices: ticker → current price (USD).
            current_positions: ticker → shares (defaults to portfolio.positions).

        Returns:
            List of trade record dicts (including rejected).
        """
        if not target_weights:
            return []

        positions: Dict[str, float] = (
            dict(current_positions)
            if current_positions is not None
            else dict(self.portfolio.positions)
        )
        total_value: float = self.portfolio.total_value
        orders: List[Dict[str, Any]] = []

        for ticker, target_weight in target_weights.items():
            try:
                current_shares: float = positions.get(ticker, 0.0)
                avg_cost: float = self.portfolio.avg_costs.get(ticker, 0.0)
                current_value: float = current_shares * avg_cost
                current_weight: float = current_value / max(total_value, 1.0)
                diff: float = target_weight - current_weight

                # Skip if difference is negligible.
                if abs(diff) < 0.005:
                    continue

                price: float = prices.get(ticker, 0.0)
                if price <= 0:
                    continue

                if diff > 0:
                    # Underweight → BUY.
                    target_value: float = diff * total_value
                    quantity: float = target_value / price
                    order = self.execute_signal(
                        ticker=ticker,
                        decision="BUY",
                        strength=min(abs(diff) / 0.20, 1.0),
                        price=price,
                        confidence=0.6,
                        strategy="bl_rebalance",
                    )
                else:
                    # Overweight → SELL.
                    target_value: float = abs(diff) * total_value
                    quantity: float = target_value / price
                    order = self.execute_signal(
                        ticker=ticker,
                        decision="SELL",
                        strength=min(abs(diff) / 0.20, 1.0),
                        price=price,
                        confidence=0.6,
                        strategy="bl_rebalance",
                    )

                if order:
                    orders.append(order)

            except Exception as exc:
                logger.warning(f"TigerExecutor: rebalance error for {ticker}: {exc}")
                continue

        return orders

    # ═══════════════════════════════════════════════════════════════
    # Internal: Execution Backends
    # ═══════════════════════════════════════════════════════════════

    def _execute_live(
        self,
        ticker: str,
        side: str,
        quantity: float,
        price: float,
        strategy: str,
    ) -> Optional[Dict[str, Any]]:
        """Place a real order via Tiger bridge.

        Args:
            ticker: Ticker.
            side: ``"BUY"`` or ``"SELL"``.
            quantity: Shares (already lot-adjusted).
            price: Limit / reference price.

        Returns:
            Trade record dict, or None on failure.
        """
        try:
            if not self.tiger.is_connected():
                logger.warning(
                    f"TigerExecutor: Tiger offline — falling back to paper for {ticker}"
                )
                return self._execute_paper(ticker, side, quantity, price, strategy)

            qty_int: int = int(quantity)
            if qty_int <= 0:
                return None

            order_result = self.tiger.place_order(
                ticker=ticker,
                action=side,
                quantity=qty_int,
                order_type="MKT",
                price=price if side == "SELL" else None,
            )

            if not order_result:
                logger.warning(f"TigerExecutor: live place_order returned None for {ticker}")
                return None

            # Build trade record.
            record: Dict[str, Any] = {
                "ticker": ticker,
                "side": side.lower(),
                "quantity": qty_int,
                "price": round(price, 2),
                "value": round(qty_int * price, 2),
                "strategy": strategy,
                "mode": "live",
                "order_id": order_result.get("order_id", ""),
                "timestamp": __import__("datetime").datetime.now().isoformat(),
            }

            # Mirror in local portfolio.
            pf_side: str = "buy" if side == "BUY" else "sell"
            self.portfolio.execute_trade(
                ticker=ticker,
                side=pf_side,
                price=price,
                quantity=float(qty_int),
                strategy=strategy,
            )

            logger.info(
                f"✅ 实盘 {side} {ticker}: {qty_int}股 @ ${price:.2f} | "
                f"订单ID: {record.get('order_id')}"
            )
            return record

        except Exception as exc:
            logger.error(f"❌ TigerExecutor live order error {ticker}: {exc}")
            return None

    def _execute_paper(
        self,
        ticker: str,
        side: str,
        quantity: float,
        price: float,
        strategy: str,
    ) -> Optional[Dict[str, Any]]:
        """Simulate an order via local portfolio.

        Args:
            ticker: Ticker.
            side: ``"BUY"`` or ``"SELL"``.
            quantity: Shares.
            price: Fill price.
            strategy: Strategy label.

        Returns:
            Trade record dict, or None if portfolio rejected.
        """
        pf_side: str = "buy" if side == "BUY" else "sell"
        trade = self.portfolio.execute_trade(
            ticker=ticker,
            side=pf_side,
            price=price,
            quantity=quantity,
            strategy=strategy,
        )

        if trade:
            trade["mode"] = "paper"
            logger.info(
                f"📝 Paper {side} {ticker}: {quantity:.2f}股 @ ${price:.2f}"
            )

        return trade

    # ═══════════════════════════════════════════════════════════════
    # Internal: Quantity Calculation
    # ═══════════════════════════════════════════════════════════════

    def _calc_quantity(
        self,
        ticker: str,
        decision: str,
        strength: float,
        price: float,
    ) -> float:
        """Calculate target share quantity from signal strength.

        Args:
            ticker: Ticker.
            decision: ``"BUY"`` or ``"SELL"``.
            strength: Signal strength 0.0–1.0.
            price: Current price (USD).

        Returns:
            Number of shares (may be fractional for paper mode).
        """
        if decision == "BUY":
            # Use available cash × strength, capped at 20% position.
            buy_value: float = self.portfolio.cash * min(strength, 0.20)
            quantity: float = buy_value / price if price > 0 else 0.0
            return quantity

        # SELL
        shares: float = self.portfolio.positions.get(ticker, 0.0)
        if shares <= 0.0:
            return 0.0
        quantity = shares * min(strength, 0.50)  # Cap sell at 50% of position
        return quantity

    # ═══════════════════════════════════════════════════════════════
    # Status
    # ═══════════════════════════════════════════════════════════════

    def get_execution_summary(self) -> Dict[str, Any]:
        """Return a summary of recent executions."""
        return {
            "mode": self.mode,
            "total_filled": len(self.filled_orders),
            "buy_count": sum(
                1 for t in self.filled_orders if t.get("side") == "buy"
            ),
            "sell_count": sum(
                1 for t in self.filled_orders if t.get("side") == "sell"
            ),
        }
