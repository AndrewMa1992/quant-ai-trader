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
        quantity: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Execute a single trading signal.

        Args:
            ticker: Stock ticker.
            decision: ``"BUY"`` / ``"SELL"`` / ``"HOLD"`` (case-insensitive).
            strength: Signal strength 0.0–1.0.
            price: Current price (USD).
            confidence: Model confidence 0.0–1.0.
            strategy: Strategy label for record-keeping.
            quantity: Optional explicit share count (rebalance path).

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

        if price <= 0.0 or confidence < 0.0:
            logger.debug(f"TigerExecutor: signal below threshold for {ticker}")
            return None

        # ── Calculate quantity ─────────────────────────────────
        if quantity is None:
            if strength <= 0.0:
                return None
            quantity = self._calc_quantity(ticker, decision_upper, strength, price)
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
                logger.info(f"📐 {ticker} lot-size aligned: {int(quantity)} → {int(rounded)} shares")
                quantity = rounded
            # Lot may exceed cash — trim to affordable whole lots
            max_cash = float(getattr(self.risk, "cash", self.portfolio.cash)) * float(
                getattr(self.risk, "MAX_CASH_USAGE", 0.95)
            )
            if quantity * price > max_cash:
                lot = _get_lot_size(ticker)
                afford = int(max_cash / price)
                if lot > 1:
                    afford = (afford // lot) * lot
                if afford <= 0:
                    return None
                quantity = float(afford)

        # ── Risk check ─────────────────────────────────────────
        side_key: str = "buy" if decision_upper == "BUY" else "sell"
        risk_report = self.risk.check_order(ticker, side_key, quantity, price)
        if not risk_report.passed:
            logger.warning(
                f"🔴 Risk rejected: {ticker} {decision_upper} | {risk_report.reason}"
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
                price: float = prices.get(ticker, 0.0)
                if price <= 0:
                    continue
                # Mark-to-market weight (NOT avg_cost — that understates winners)
                current_value: float = current_shares * price
                current_weight: float = current_value / max(total_value, 1.0)
                diff: float = target_weight - current_weight

                # Skip if difference is negligible.
                if abs(diff) < 0.005:
                    continue

                target_value: float = abs(diff) * total_value
                quantity: float = target_value / price
                if diff > 0:
                    order = self.execute_signal(
                        ticker=ticker,
                        decision="BUY",
                        strength=min(abs(diff) / 0.20, 1.0),
                        price=price,
                        confidence=0.6,
                        strategy="bl_rebalance",
                        quantity=quantity,
                    )
                else:
                    # Cap sell to holdings
                    quantity = min(quantity, current_shares)
                    order = self.execute_signal(
                        ticker=ticker,
                        decision="SELL",
                        strength=min(abs(diff) / 0.20, 1.0),
                        price=price,
                        confidence=0.6,
                        strategy="bl_rebalance",
                        quantity=quantity,
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
                order_type="LMT" if price and float(price) > 0 else "MKT",
                price=price if price and float(price) > 0 else None,
            )

            from shared.tiger_orders import order_was_accepted

            if not order_was_accepted(order_result):
                logger.warning(
                    f"TigerExecutor: live place_order not accepted for {ticker}: {order_result}"
                )
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
                f"✅ Live {side} {ticker}: {qty_int} shares @ ${price:.2f} | "
                f"order ID: {record.get('order_id')}"
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
        """Paper fill: optionally route to Tiger paper account, always update local book.

        When ``QAT_TIGER_PAPER_TRADING=true`` and Tiger is connected, place a real
        paper-account order then mirror into PortfolioManager. Otherwise local sim only.
        """
        tiger_order_id = None
        try:
            from configs.settings import settings

            use_tiger_paper = bool(getattr(settings, "TIGER_PAPER_TRADING", False))
        except Exception:
            use_tiger_paper = False

        if use_tiger_paper and self.tiger is not None:
            try:
                # Skip broker submit when Tiger paper has no buying power —
                # still fill locally so US paper book can trade.
                tiger_cash_ok = True
                try:
                    if hasattr(self.tiger, "get_account_info"):
                        acct = self.tiger.get_account_info()
                        if acct is not None:
                            tc = float(acct.get("cash", 0) or 0)
                            tv = float(
                                acct.get("total_value", 0)
                                or acct.get("nav", 0)
                                or acct.get("net_liquidation", 0)
                                or 0
                            )
                            bp = float(
                                acct.get("buying_power", 0)
                                or acct.get("available_funds", 0)
                                or 0
                            )
                            if max(tc, tv, bp) <= 1.0 and side.upper() == "BUY":
                                tiger_cash_ok = False
                                logger.info(
                                    f"Tiger paper cash/NAV/BP≈0 — skip broker BUY for {ticker}, local sim only"
                                )
                except Exception:
                    tiger_cash_ok = True

                connected = False
                if hasattr(self.tiger, "is_connected"):
                    connected = bool(self.tiger.is_connected())
                elif hasattr(self.tiger, "connect"):
                    connected = True
                if tiger_cash_ok and (connected or hasattr(self.tiger, "place_order")):
                    qty_int = max(1, int(quantity))
                    order_result = None
                    if hasattr(self.tiger, "place_order"):
                        # Limit + outside_rth/FULL so the fill shows in the Tiger app
                        # overnight and in pre/post. MKT is regular-hours only.
                        order_result = self.tiger.place_order(
                            ticker=ticker,
                            action=side,
                            quantity=qty_int,
                            order_type="LMT",
                            price=price if price and float(price) > 0 else None,
                        )
                    from shared.tiger_orders import order_was_accepted

                    if order_was_accepted(order_result):
                        tiger_order_id = (
                            order_result.get("order_id")
                            or order_result.get("id")
                            or order_result.get("orderId")
                        )
                        logger.info(
                            f"Tiger paper {side} {ticker}: {qty_int} shares | id={tiger_order_id}"
                        )
                    else:
                        err = ""
                        if isinstance(order_result, dict):
                            err = str(
                                order_result.get("error")
                                or order_result.get("status")
                                or ""
                            )
                        logger.warning(
                            f"Tiger paper place_order did not reach the app for {ticker}"
                            + (f" ({err})" if err else "")
                            + " — local sim only"
                        )
            except Exception as exc:
                logger.warning(f"Tiger paper order failed ({ticker}): {exc} — local sim only")

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
            if tiger_order_id:
                trade["tiger_order_id"] = tiger_order_id
                trade["tiger_paper"] = True
            try:
                from shared.tiger_persist import persist_fill

                persist_fill(
                    ticker=ticker,
                    side=side,
                    quantity=quantity,
                    price=price,
                    order_id=str(tiger_order_id) if tiger_order_id else None,
                    strategy=strategy,
                    is_paper=True,
                )
            except Exception as exc:
                logger.debug(f"persist_fill skipped: {exc}")
            logger.info(
                f"📝 Paper {side} {ticker}: {quantity:.2f} shares @ ${price:.2f}"
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
        """Calculate target share quantity from signal strength (NAV-aware)."""
        try:
            from shared.capital_policy import build_capital_policy

            pol = build_capital_policy(self.portfolio.total_value)
            strength_cap = pol.buy_strength_cap
        except Exception:
            strength_cap = 0.20

        if decision == "BUY":
            buy_value: float = self.portfolio.cash * min(strength, strength_cap)
            # Also respect max position vs NAV
            max_pos = float(getattr(self.risk, "MAX_POSITION_SIZE", 0.20))
            max_by_nav = self.portfolio.total_value * max_pos
            buy_value = min(buy_value, max_by_nav)
            quantity: float = buy_value / price if price > 0 else 0.0
            return quantity

        shares: float = self.portfolio.positions.get(ticker, 0.0)
        if shares <= 0.0:
            return 0.0
        return shares * min(strength, 0.50)

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
