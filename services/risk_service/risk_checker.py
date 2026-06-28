"""services/risk_service/risk_checker.py – Pre-trade risk checker.

Integrates multiple risk gates into a single `check()` entry point:
  1. CircuitBreaker  – halt/daily-loss/cool-down (optional external CB)
  2. Position limit  – single ticker ≤ MAX_SINGLE_STOCK_EXPOSURE × NAV
  3. Order risk      – order_value ≤ single_order_limit × NAV
  4. VaR threshold   – portfolio VaR ≤ VAR_LIMIT_PCT × NAV
  5. CVaR threshold  – portfolio CVaR ≤ CVAR_LIMIT_PCT × NAV

The class is designed to be instantiated once during the risk-service lifespan
and shared across all /check endpoint calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger

from configs.risk_limits import RISK_LIMITS


# ---------------------------------------------------------------------------
# RiskLimits configuration
# ---------------------------------------------------------------------------

@dataclass
class RiskLimits:
    """Per-instance risk limit overrides.

    Defaults are read from the system-wide RISK_LIMITS singleton
    (configs/risk_limits.py).  Pass keyword arguments to override
    specific thresholds for testing or environment tuning.

    Attributes:
        single_ticker_pct: Max single ticker exposure as fraction of NAV.
        max_order_risk_pct: Max single-order value as fraction of NAV.
        daily_trade_limit: Max number of trades per day.
        net_exposure_limit: Max net exposure (long − short) / NAV.
        var_limit_pct: Daily VaR limit as fraction of NAV.
        cvar_limit_pct: Daily CVaR limit as fraction of NAV.
        max_drawdown_pct: Max portfolio drawdown before blocking orders.
    """

    single_ticker_pct: float = field(
        default_factory=lambda: RISK_LIMITS.MAX_SINGLE_STOCK_EXPOSURE,
    )
    max_order_risk_pct: float = 0.02
    daily_trade_limit: int = 50
    net_exposure_limit: float = field(
        default_factory=lambda: RISK_LIMITS.MAX_NET_EXPOSURE,
    )
    var_limit_pct: float = field(
        default_factory=lambda: RISK_LIMITS.VAR_LIMIT,
    )
    cvar_limit_pct: float = field(
        default_factory=lambda: RISK_LIMITS.CVAR_LIMIT,
    )
    max_drawdown_pct: float = field(
        default_factory=lambda: RISK_LIMITS.MAX_DRAWDOWN_PORTFOLIO,
    )


# ---------------------------------------------------------------------------
# RiskChecker
# ---------------------------------------------------------------------------

class RiskChecker:
    """Pre-trade risk checker integrating CircuitBreaker + RiskLimits.

    Usage::

        checker = RiskChecker()
        result = checker.check(
            ticker="AAPL",
            quantity=100,
            price=185.50,
            portfolio_state={"total_value": 100_000, "positions": {"AAPL": 50}},
        )
        # result is a dict compatible with RiskCheckResult(**result)

    Optionally accepts an external `CircuitBreaker` instance::

        from services.execution_service.live.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker()
        cb.set_nav(100_000)
        checker = RiskChecker(circuit_breaker=cb)
    """

    def __init__(
        self,
        limits: Optional[RiskLimits] = None,
        circuit_breaker: Optional[Any] = None,
    ) -> None:
        """Initialise RiskChecker.

        Args:
            limits: Optional RiskLimits overrides.  If None, defaults are used.
            circuit_breaker: Optional CircuitBreaker instance for Gate 1.
        """
        self._limits: RiskLimits = limits or RiskLimits()
        self._circuit_breaker: Optional[Any] = circuit_breaker

        # Internal state
        self._trade_count_today: int = 0
        self._last_trade_date: str = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(
        self,
        ticker: str,
        quantity: int,
        price: float,
        portfolio_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run all pre-trade risk checks sequentially.

        Checks are executed in priority order.  The first failing check
        short-circuits and returns immediately with `passed=False`.

        Args:
            ticker: Stock ticker symbol (e.g. "AAPL").
            quantity: Number of shares in the order.
            price: Execution price per share.
            portfolio_state: Optional snapshot dict with keys:
                - total_value (float): Portfolio NAV.
                - cash (float): Available cash.
                - positions (dict[str, float]): Ticker → current shares held.
                - tickers (list[str]): All tickers currently held.
                - weights (list[float]): Corresponding portfolio weights.

        Returns:
            Dict with keys compatible with ``RiskCheckResult``:
                - passed (bool)
                - reason (str)
                - warnings (list[str])
                - sanitized_weights (dict[str, float] | None)
        """
        warnings: List[str] = []
        portfolio_state = portfolio_state or {}

        # ── Gate 1: Circuit Breaker ──────────────────────────
        cb_result = self._check_circuit_breaker(ticker, quantity, price)
        if not cb_result["passed"]:
            cb_result["warnings"] = warnings
            cb_result["sanitized_weights"] = None
            return cb_result
        if cb_result.get("warning"):
            warnings.append(cb_result["warning"])

        # ── Gate 2: Position Limit (single ticker) ───────────
        pos_result = self._check_position_limit(ticker, quantity, price, portfolio_state)
        if not pos_result["passed"]:
            return {
                "passed": False,
                "reason": pos_result["reason"],
                "warnings": warnings,
                "sanitized_weights": None,
            }
        if pos_result.get("warning"):
            warnings.append(pos_result["warning"])

        # ── Gate 3: Order Risk (single order value) ──────────
        order_result = self._check_order_risk(quantity, price, portfolio_state)
        if not order_result["passed"]:
            return {
                "passed": False,
                "reason": order_result["reason"],
                "warnings": warnings,
                "sanitized_weights": None,
            }
        if order_result.get("warning"):
            warnings.append(order_result["warning"])

        # ── Gate 4: Daily Trade Count ────────────────────────
        trade_result = self._check_daily_trade_limit()
        if not trade_result["passed"]:
            return {
                "passed": False,
                "reason": trade_result["reason"],
                "warnings": warnings,
                "sanitized_weights": None,
            }
        if trade_result.get("warning"):
            warnings.append(trade_result["warning"])

        # ── Gate 5: Net Exposure ─────────────────────────────
        exposure_result = self._check_net_exposure(ticker, quantity, price, portfolio_state)
        if not exposure_result["passed"]:
            return {
                "passed": False,
                "reason": exposure_result["reason"],
                "warnings": warnings,
                "sanitized_weights": None,
            }
        if exposure_result.get("warning"):
            warnings.append(exposure_result["warning"])

        # ── Gate 6: VaR Threshold ────────────────────────────
        var_result = self._check_var(portfolio_state)
        if not var_result["passed"]:
            return {
                "passed": False,
                "reason": var_result["reason"],
                "warnings": warnings,
                "sanitized_weights": None,
            }
        if var_result.get("warning"):
            warnings.append(var_result["warning"])

        # ── Gate 7: CVaR Threshold ───────────────────────────
        cvar_result = self._check_cvar(portfolio_state)
        if not cvar_result["passed"]:
            return {
                "passed": False,
                "reason": cvar_result["reason"],
                "warnings": warnings,
                "sanitized_weights": None,
            }
        if cvar_result.get("warning"):
            warnings.append(cvar_result["warning"])

        # ── All gates passed ─────────────────────────────────
        logger.info(
            f"✅ RiskCheck PASSED | ticker={ticker} qty={quantity} "
            f"price={price:.2f} order_value={quantity * price:.2f}"
            + (f" | warnings={len(warnings)}" if warnings else ""),
        )
        return {
            "passed": True,
            "reason": "ALL_PASSED",
            "warnings": warnings,
            "sanitized_weights": None,
        }

    # ------------------------------------------------------------------
    # Gate implementations
    # ------------------------------------------------------------------

    def _check_circuit_breaker(
        self,
        ticker: str,
        quantity: int,
        price: float,
    ) -> Dict[str, Any]:
        """Gate 1: Circuit breaker status and per-order allowance.

        If an external CircuitBreaker is wired, delegates to its
        ``allow_order()`` / ``status()`` methods.  Otherwise this gate
        passes through (no-op).
        """
        if self._circuit_breaker is None:
            return {"passed": True}

        try:
            # Check if the breaker exposes a status dict
            if hasattr(self._circuit_breaker, "status"):
                status: dict = self._circuit_breaker.status()
                if status.get("halted"):
                    reason = status.get("halt_reason", "Circuit breaker halted")
                    return {"passed": False, "reason": f"CircuitBreaker: {reason}"}
                if status.get("cooling_active"):
                    remaining: float = status.get("cooling_remaining_minutes", 0.0)
                    return {
                        "passed": False,
                        "reason": (
                            f"CircuitBreaker: cool-down active, "
                            f"{remaining:.0f} min remaining"
                        ),
                    }

            # Delegate to allow_order() if available
            if hasattr(self._circuit_breaker, "allow_order"):
                allowed: bool = self._circuit_breaker.allow_order(ticker, quantity, price)
                if not allowed:
                    return {
                        "passed": False,
                        "reason": "CircuitBreaker: order rejected by circuit breaker",
                    }

            return {"passed": True}

        except Exception as exc:
            logger.warning(f"CircuitBreaker check error (failing open): {exc}")
            return {
                "passed": True,
                "warning": f"CircuitBreaker error: {exc}",
            }

    def _check_position_limit(
        self,
        ticker: str,
        quantity: int,
        price: float,
        portfolio_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Gate 2: Single-ticker position limit.

        Ensures the ticker's post-trade weight does not exceed
        ``single_ticker_pct`` of portfolio NAV.
        """
        nav: float = portfolio_state.get("total_value", 0.0)
        if nav <= 0:
            return {"passed": True, "warning": "Portfolio NAV unavailable; skipping position limit check"}

        positions: Dict[str, float] = portfolio_state.get("positions", {})
        current_shares: float = float(positions.get(ticker, 0.0))
        order_value: float = quantity * price
        price_val: float = price

        # Current exposure
        current_value: float = current_shares * price_val

        # Post-trade exposure
        post_trade_value: float = current_value + order_value
        post_trade_weight: float = post_trade_value / nav

        limit: float = self._limits.single_ticker_pct

        if post_trade_weight > limit:
            return {
                "passed": False,
                "reason": (
                    f"Position limit: {ticker} post-trade weight "
                    f"{post_trade_weight:.2%} exceeds limit {limit:.2%}"
                ),
            }

        return {"passed": True}

    def _check_order_risk(
        self,
        quantity: int,
        price: float,
        portfolio_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Gate 3: Single-order value relative to portfolio NAV.

        Ensures the order value is no more than ``max_order_risk_pct`` of NAV.
        """
        nav: float = portfolio_state.get("total_value", 0.0)
        if nav <= 0:
            return {"passed": True}

        order_value: float = quantity * price
        order_weight: float = order_value / nav
        limit: float = self._limits.max_order_risk_pct

        if order_weight > limit:
            return {
                "passed": False,
                "reason": (
                    f"Order risk: ${order_value:,.2f} ({order_weight:.2%} of NAV) "
                    f"exceeds single-order limit {limit:.2%}"
                ),
            }

        return {"passed": True}

    def _check_daily_trade_limit(self) -> Dict[str, Any]:
        """Gate 4: Daily trade count limit.

        Reset automatically on date change.  This is a soft counter —
        the actual trade is recorded later via ``record_trade()``.
        """
        from datetime import datetime, timezone

        today: str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._last_trade_date:
            self._trade_count_today = 0
            self._last_trade_date = today

        limit: int = self._limits.daily_trade_limit
        if self._trade_count_today >= limit:
            return {
                "passed": False,
                "reason": f"Daily trade limit: {self._trade_count_today}/{limit} trades executed today",
            }

        return {"passed": True}

    def _check_net_exposure(
        self,
        ticker: str,
        quantity: int,
        price: float,
        portfolio_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Gate 5: Net exposure limit.

        Simulates the post-trade net exposure (long − short) / NAV and
        ensures it does not exceed ``net_exposure_limit``.
        """
        nav: float = portfolio_state.get("total_value", 0.0)
        if nav <= 0:
            return {"passed": True}

        positions: Dict[str, float] = portfolio_state.get("positions", {})
        current_shares: float = float(positions.get(ticker, 0.0))
        price_val: float = price

        # Estimate current portfolio long and short values.
        # For a long-only book this simply sums all positions.
        current_long: float = 0.0
        current_short: float = 0.0

        for sym, shares in positions.items():
            pos_value: float = float(shares) * price_val if sym == ticker else float(shares) * price_val
            # Use price for the target ticker; for others we approximate with same price
            # since we don't have individual prices in portfolio_state.
            # A real implementation would use last prices from a price cache.
            if float(shares) > 0:
                current_long += pos_value
            else:
                current_short += abs(pos_value)

        # Add the new order
        order_value: float = quantity * price
        if quantity > 0:
            current_long += order_value
        else:
            current_short += abs(order_value)

        net_exposure: float = (current_long - current_short) / nav
        limit: float = self._limits.net_exposure_limit

        if abs(net_exposure) > limit:
            return {
                "passed": False,
                "reason": (
                    f"Net exposure: {net_exposure:.2%} exceeds limit {limit:.2%}"
                ),
            }

        return {"passed": True}

    def _check_var(self, portfolio_state: Dict[str, Any]) -> Dict[str, Any]:
        """Gate 6: Value-at-Risk threshold.

        Attempts to compute portfolio VaR using the local VaRCalculator.
        If tickers + weights are provided in portfolio_state, a proper
        VaR estimate is computed; otherwise this gate passes with a
        warning.
        """
        nav: float = portfolio_state.get("total_value", 0.0)
        if nav <= 0:
            return {"passed": True}

        tickers: list = portfolio_state.get("tickers", [])
        weights: list = portfolio_state.get("weights", [])

        if not tickers or not weights or len(tickers) != len(weights):
            return {
                "passed": True,
                "warning": "No tickers/weights in portfolio_state; VaR check skipped",
            }

        try:
            from services.risk_service.risk_measures.var import VaRCalculator

            calc = VaRCalculator(confidence=RISK_LIMITS.VAR_CONF)
            var_result = calc.compute(
                tickers=tickers,
                weights=weights,
                method="historical",
            )

            var_value: float = var_result.get("var", 0.0)
            var_limit: float = self._limits.var_limit_pct * nav

            if var_value > var_limit:
                return {
                    "passed": False,
                    "reason": (
                        f"VaR: ${var_value * nav:,.2f} "
                        f"({var_value:.2%}) exceeds limit "
                        f"${var_limit:,.2f} ({self._limits.var_limit_pct:.2%})"
                    ),
                }

            return {"passed": True}

        except Exception as exc:
            logger.warning(f"VaR check error (failing open): {exc}")
            return {
                "passed": True,
                "warning": f"VaR computation failed: {exc}",
            }

    def _check_cvar(self, portfolio_state: Dict[str, Any]) -> Dict[str, Any]:
        """Gate 7: Conditional Value-at-Risk threshold.

        Same approach as the VaR gate — uses local CVaRCalculator when
        tickers+weights are available.
        """
        nav: float = portfolio_state.get("total_value", 0.0)
        if nav <= 0:
            return {"passed": True}

        tickers: list = portfolio_state.get("tickers", [])
        weights: list = portfolio_state.get("weights", [])

        if not tickers or not weights or len(tickers) != len(weights):
            return {
                "passed": True,
                "warning": "No tickers/weights in portfolio_state; CVaR check skipped",
            }

        try:
            from services.risk_service.risk_measures.cvar import CVaRCalculator

            calc = CVaRCalculator(confidence=RISK_LIMITS.CVAR_CONF)
            cvar_result = calc.compute(tickers=tickers, weights=weights)

            cvar_value: float = cvar_result.get(
                "cvar_95",
                cvar_result.get("cvar", 0.0),
            )
            cvar_limit: float = self._limits.cvar_limit_pct * nav

            if cvar_value > cvar_limit:
                return {
                    "passed": False,
                    "reason": (
                        f"CVaR: ${cvar_value * nav:,.2f} "
                        f"({cvar_value:.2%}) exceeds limit "
                        f"${cvar_limit:,.2f} ({self._limits.cvar_limit_pct:.2%})"
                    ),
                }

            return {"passed": True}

        except Exception as exc:
            logger.warning(f"CVaR check error (failing open): {exc}")
            return {
                "passed": True,
                "warning": f"CVaR computation failed: {exc}",
            }

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def record_trade(self, ticker: str, quantity: int, pnl: float) -> None:
        """Record a completed trade for daily-count and breaker tracking.

        Call this **after** an order has been filled.

        Args:
            ticker: Stock symbol.
            quantity: Number of shares traded.
            pnl: Realized profit/loss for this trade.
        """
        self._trade_count_today += 1

        if self._circuit_breaker is not None and hasattr(
            self._circuit_breaker, "record_trade"
        ):
            try:
                self._circuit_breaker.record_trade(pnl)
            except Exception as exc:
                logger.warning(f"Failed to record trade in circuit breaker: {exc}")

    def set_circuit_breaker(self, cb: Any) -> None:
        """Wire an external CircuitBreaker after construction.

        Args:
            cb: A CircuitBreaker instance.
        """
        self._circuit_breaker = cb
        logger.info("RiskChecker: external CircuitBreaker wired")

    def update_limits(self, **overrides: Any) -> None:
        """Update specific risk limits at runtime.

        Keyword Args:
            single_ticker_pct: Max single ticker exposure.
            max_order_risk_pct: Max single order as fraction of NAV.
            daily_trade_limit: Max trades per day.
            net_exposure_limit: Max net exposure.
            var_limit_pct: VaR limit.
            cvar_limit_pct: CVaR limit.
            max_drawdown_pct: Max drawdown.
        """
        for key, value in overrides.items():
            if hasattr(self._limits, key):
                setattr(self._limits, key, value)
                logger.info(f"RiskChecker limit updated: {key} = {value}")
            else:
                logger.warning(f"Unknown risk limit key: {key}")

    def status(self) -> Dict[str, Any]:
        """Return current risk checker status for diagnostics.

        Returns:
            Dict with active limits, circuit breaker status, and trade counter.
        """
        result: Dict[str, Any] = {
            "limits": {
                "single_ticker_pct": self._limits.single_ticker_pct,
                "max_order_risk_pct": self._limits.max_order_risk_pct,
                "daily_trade_limit": self._limits.daily_trade_limit,
                "net_exposure_limit": self._limits.net_exposure_limit,
                "var_limit_pct": self._limits.var_limit_pct,
                "cvar_limit_pct": self._limits.cvar_limit_pct,
                "max_drawdown_pct": self._limits.max_drawdown_pct,
            },
            "daily_trades": self._trade_count_today,
            "last_trade_date": self._last_trade_date,
            "circuit_breaker_wired": self._circuit_breaker is not None,
        }

        if self._circuit_breaker is not None and hasattr(self._circuit_breaker, "status"):
            try:
                result["circuit_breaker"] = self._circuit_breaker.status()
            except Exception as exc:
                result["circuit_breaker_error"] = str(exc)

        return result
