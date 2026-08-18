"""
RiskManager — v2 risk-control manager
=====================================
Replaces ``backend.trading_engine.risk_manager.RiskManager``.
Zero ``import backend.`` — all constants are self-contained.

Implements:
  P0-1: Real-order execution safeguard
  P0-2: Circuit breaker (daily loss ≥ 5% / drawdown ≥ 25%)
  P1-1: Leverage iron law (leverage ≥ 1.001 → block)
  P1-2: Daily trade limit
  P1-3: Short-position auto-fix
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger


# ── Default risk constants (self-contained, no backend.config) ──
DAILY_LOSS_LIMIT: float = 0.05       # 5% daily loss → circuit breaker
MAX_DRAWDOWN: float = 0.25           # 25% peak drawdown → circuit breaker
CIRCUIT_BREAKER_COOLDOWN: int = 3600  # 1 hour cool-down
MAX_CASH_USAGE: float = 0.95         # Max fraction of cash for a single buy
MAX_POSITION_SIZE: float = 0.20      # Max single-position weight
MIN_TRADE_VALUE: float = 100.0       # Minimum notional per trade
DEFAULT_BREAKER_MODE: str = "hard"


@dataclass
class RiskReport:
    """Risk-check result returned by all RiskManager check methods.

    Attributes:
        passed: Whether the order / operation is approved.
        reason: Human-readable reason for rejection (empty if passed).
        warnings: Non-blocking warning messages.
        circuit_breaker: True if the circuit breaker blocked this check.
        daily_limit_reached: True if the daily trade cap was hit.
        leverage_blocked: True if leverage was detected.
        details: Arbitrary additional context.
    """

    passed: bool = True
    reason: str = ""
    warnings: List[str] = field(default_factory=list)
    circuit_breaker: bool = False
    daily_limit_reached: bool = False
    leverage_blocked: bool = False
    details: Dict[str, Any] = field(default_factory=dict)


class RiskManager:
    """Unified risk-control manager for v2 trading pipeline.

    Performs pre-trade checks, circuit breaker monitoring, leverage
    enforcement, and short-position auto-fix.  All constants are
    self-contained — zero backend imports.

    Typical usage inside a trading cycle:

        >>> risk = RiskManager()
        >>> risk.sync_portfolio_value(105000, 45000)
        >>> report = risk.check_circuit_breaker()
        >>> if report.passed:
        ...     order_report = risk.check_order("AAPL", "buy", 100, 180.0)
    """

    # ── Risk thresholds (override in constructor if needed) ────
    DAILY_LOSS_LIMIT: float = DAILY_LOSS_LIMIT
    MAX_DRAWDOWN: float = MAX_DRAWDOWN
    CIRCUIT_BREAKER_COOLDOWN: int = CIRCUIT_BREAKER_COOLDOWN
    MAX_CASH_USAGE: float = MAX_CASH_USAGE
    MAX_POSITION_SIZE: float = MAX_POSITION_SIZE
    MIN_TRADE_VALUE: float = MIN_TRADE_VALUE

    def __init__(
        self,
        initial_capital: float = 100000.0,
        breaker_mode: str = DEFAULT_BREAKER_MODE,
        max_daily_trades: int = 0,
    ) -> None:
        # ── Portfolio snapshot ─────────────────────────────────
        self.portfolio_value: float = initial_capital
        self.cash: float = initial_capital
        self.positions: Dict[str, float] = {}          # ticker → shares
        self.position_values: Dict[str, float] = {}    # ticker → market value

        # ── Draw-down tracking ────────────────────────────────
        self.peak_value: float = initial_capital
        self.daily_start_value: float = 0.0            # 0 = uninitialised

        # ── Circuit breaker ───────────────────────────────────
        self.circuit_breaker_triggered: bool = False
        self.circuit_breaker_time: Optional[datetime] = None
        self.breaker_mode: str = breaker_mode           # "hard" | "warn"

        # ── Daily trade gate (P1-2) ───────────────────────────
        self.trades_today: int = 0
        self.max_daily_trades: int = max_daily_trades

        # ── Trade history (lightweight) ───────────────────────
        self.trade_history: List[Dict[str, Any]] = []

        # ── Tiger sync flag (P0 fix: prevent false circuit breaker) ─
        self._tiger_synced: bool = False

        logger.info(
            f"RiskManager initialised | mode={breaker_mode} | "
            f"capital=${initial_capital:,.0f} | "
            f"daily_loss_limit={self.DAILY_LOSS_LIMIT:.0%} | "
            f"max_drawdown={self.MAX_DRAWDOWN:.0%}"
        )

    # ═══════════════════════════════════════════════════════════════
    # P0-2: Circuit Breaker
    # ═══════════════════════════════════════════════════════════════

    def check_circuit_breaker(self) -> RiskReport:
        """Portfolio-level circuit breaker check.

        Rules:
        1. Daily loss ≥ DAILY_LOSS_LIMIT (default 5%) → breaker
        2. Peak drawdown ≥ MAX_DRAWDOWN (default 25%) → breaker
        3. Already in cool-down period → maintain breaker

        On first call (daily_start_value == 0), initialises
        daily_start_value from current portfolio_value — a clean
        start avoids false positives.

        Returns:
            RiskReport with ``circuit_breaker`` flag set when triggered.
        """
        report = RiskReport()
        is_warn: bool = self.breaker_mode == "warn"

        # ── Lazy initialise daily start on first call ──────────
        if self.daily_start_value <= 0.0:
            self.daily_start_value = self.portfolio_value
            self.peak_value = max(self.peak_value, self.portfolio_value)
            logger.info(
                f"🔰 RiskManager: daily start initialised at ${self.daily_start_value:,.2f}"
            )
            return report  # first cycle always passes

        # ── Cool-down check ────────────────────────────────────
        if self.circuit_breaker_triggered and self.circuit_breaker_time is not None:
            cooldown_elapsed: float = (
                datetime.now() - self.circuit_breaker_time
            ).total_seconds()
            if cooldown_elapsed < self.CIRCUIT_BREAKER_COOLDOWN:
                remaining: int = int(self.CIRCUIT_BREAKER_COOLDOWN - cooldown_elapsed)
                report.circuit_breaker = True
                report.passed = False
                report.reason = (
                    f"🚨 熔断冷却中: {int(cooldown_elapsed)}s / "
                    f"{self.CIRCUIT_BREAKER_COOLDOWN}s (剩余 {remaining}s)"
                )
                report.details["breaker_mode"] = self.breaker_mode
                report.details["cooldown_remaining_s"] = remaining
                return report
            # Cool-down expired → auto-lift.
            logger.info("🟢 熔断冷却期结束，恢复交易")
            self.circuit_breaker_triggered = False
            self.circuit_breaker_time = None

        # ── Daily loss check ───────────────────────────────────
        daily_pnl: float = self.portfolio_value - self.daily_start_value
        daily_loss_pct: float = -daily_pnl / max(self.daily_start_value, 1.0)

        # ── Guard: auto-calibrate on extreme gap from first Tiger sync ─
        if abs(daily_loss_pct) > 0.10 and not self._tiger_synced:
            logger.warning(
                f"⚠️ 检测到异常日损益 {daily_loss_pct:.1%} (pv=${self.portfolio_value:,.0f} "
                f"vs daily_start=${self.daily_start_value:,.0f}) — "
                f"推测尚未完成 Tiger 同步，自动校准并跳过本轮"
            )
            self.daily_start_value = self.portfolio_value
            self.peak_value = self.portfolio_value
            self._tiger_synced = True
            return report  # skip check this cycle, recalibrated

        if daily_loss_pct >= self.DAILY_LOSS_LIMIT:
            report.circuit_breaker = True
            report.passed = is_warn  # warn: still pass; hard: block
            msg: str = (
                f"{'⚠️ 断路器告警' if is_warn else '🚨 熔断触发'}: "
                f"当日亏损 {daily_loss_pct:.2%} ≥ 限制 {self.DAILY_LOSS_LIMIT:.0%}"
            )
            report.reason = msg
            if not is_warn:
                self.circuit_breaker_triggered = True
                self.circuit_breaker_time = datetime.now()
            report.details["daily_pnl_pct"] = round(daily_loss_pct, 4)
            (logger.warning if is_warn else logger.error)(msg)

        # ── Drawdown check ─────────────────────────────────────
        if not report.circuit_breaker and self.peak_value > self.portfolio_value > 0:
            current_dd: float = (self.peak_value - self.portfolio_value) / self.peak_value
            # Extreme DD (>90%) is treated as data noise ONLY before Tiger sync.
            # After sync, real wipeouts must still trip the breaker.
            anomaly_skip = current_dd >= 0.90 and not self._tiger_synced
            if (not anomaly_skip) and current_dd >= self.MAX_DRAWDOWN:
                report.circuit_breaker = True
                report.passed = is_warn  # warn: still pass; hard: block
                msg2: str = (
                    f"{'⚠️ 断路器告警' if is_warn else '🚨 熔断触发'}: "
                    f"最大回撤 {current_dd:.2%} ≥ 限制 {self.MAX_DRAWDOWN:.0%}"
                )
                report.reason = msg2 if not report.reason else report.reason + "; " + msg2
                if not is_warn:
                    self.circuit_breaker_triggered = True
                    self.circuit_breaker_time = datetime.now()
                report.details["current_drawdown"] = round(current_dd, 4)
            elif anomaly_skip:
                logger.warning(
                    f"⚠️ 检测到异常回撤 {current_dd:.2%}，尚未完成 Tiger 同步，"
                    f"跳过熔断 (peak=${self.peak_value:,.0f}, pv=${self.portfolio_value:,.0f})"
                )

        report.details["daily_start_value"] = self.daily_start_value
        report.details["breaker_mode"] = self.breaker_mode
        report.details["portfolio_value"] = self.portfolio_value

        return report

    # ═══════════════════════════════════════════════════════════════
    # P0-2: Emergency Liquidation
    # ═══════════════════════════════════════════════════════════════

    def liquidate_all(
        self,
        prices: Dict[str, float],
        tiger_bridge: Any,
    ) -> List[Dict[str, Any]]:
        """Liquidate all positions — called on circuit breaker.

        In live mode (tiger_bridge connected), sends real sell orders
        via ``tiger_bridge.place_order``. In paper mode, returns a
        list of virtual order dicts for logging / back-testing.

        Args:
            prices: ticker → current_price (USD).
            tiger_bridge: ``shared.tiger_bridge`` module reference.

        Returns:
            List of liquidation order dicts.
        """
        if not self.positions:
            logger.info("📭 无持仓需要平仓")
            return []

        logger.warning(f"🚨 执行组合级平仓: {len(self.positions)} 只持仓")
        liquidation_records: List[Dict[str, Any]] = []

        live_mode: bool = False
        try:
            from shared.execution_mode import can_place_live_order

            live_mode = can_place_live_order(tiger_bridge)
        except Exception:
            live_mode = False
        if not live_mode:
            logger.info("📭 模拟/paper 模式平仓 — 仅更新本地持仓，不下实盘单")

        for ticker, shares in list(self.positions.items()):
            if shares <= 0:
                continue

            price: float = prices.get(ticker, 0.0)
            if price <= 0:
                logger.warning(f"⚠️ {ticker} 无有效价格，跳过平仓")
                continue

            value: float = shares * price
            record: Dict[str, Any] = {
                "ticker": ticker,
                "side": "sell",
                "shares": shares,
                "price": price,
                "value": round(value, 2),
                "reason": "circuit_breaker_liquidation",
                "timestamp": datetime.now().isoformat(),
            }

            if live_mode:
                try:
                    qty_int: int = int(shares)
                    if qty_int > 0:
                        order_result = tiger_bridge.place_order(
                            ticker=ticker,
                            action="SELL",
                            quantity=qty_int,
                            order_type="MKT",
                        )
                        if order_result:
                            record["order_id"] = order_result.get("order_id", "")
                            logger.info(
                                f"  📉 实盘平仓 {ticker}: {qty_int}股 @ ${price:.2f} = ${value:,.2f}"
                            )
                        else:
                            record["order_failed"] = True
                            logger.warning(f"  ⚠️ 平仓下单返回空: {ticker}")
                except Exception as exc:
                    record["order_failed"] = True
                    logger.error(f"  ❌ 平仓下单异常 {ticker}: {exc}")
            else:
                logger.info(
                    f"  📉 Paper平仓 {ticker}: {shares:.0f}股 @ ${price:.2f} = ${value:,.2f}"
                )

            # Update local state regardless of live/paper.
            self.cash += value
            self.position_values.pop(ticker, None)
            self.positions[ticker] = 0.0

            liquidation_records.append(record)

        # Recalculate portfolio value.
        remaining_value: float = sum(
            self.positions.get(t, 0.0) * prices.get(t, 0.0)
            for t in self.positions
        )
        self.portfolio_value = self.cash + remaining_value

        logger.warning(
            f"✅ 平仓完成: {len(liquidation_records)} 笔, "
            f"现金 ${self.cash:,.2f}, 总资产 ${self.portfolio_value:,.2f}"
        )
        return liquidation_records

    # ═══════════════════════════════════════════════════════════════
    # P1-1: Leverage Iron Law
    # ═══════════════════════════════════════════════════════════════

    def check_leverage(self, tiger_account: Optional[Dict[str, Any]]) -> bool:
        """Check Tiger account for leverage.

        Args:
            tiger_account: Dict from ``tiger_bridge.get_account_info()``
                with at minimum a ``leverage`` key.

        Returns:
            True if leverage ≥ 1.001 (BLOCKED).  False if safe.
        """
        if tiger_account is None:
            return False

        leverage: float = float(tiger_account.get("leverage", 1.0))
        if leverage > 1.001:
            logger.warning(
                f"🚫 杠杆铁律阻止: Tiger杠杆率 {leverage:.4f} > 1.0 | "
                f"必须先消除杠杆才能交易"
            )
            return True
        return False

    # ═══════════════════════════════════════════════════════════════
    # P1-2: Daily Trade Limit
    # ═══════════════════════════════════════════════════════════════

    def check_daily_limit(self) -> bool:
        """Check whether the daily trade cap has been reached.

        Returns:
            True if ``trades_today >= max_daily_trades`` AND
            ``max_daily_trades > 0`` (BLOCKED).
        """
        if self.max_daily_trades <= 0:
            return False
        if self.trades_today >= self.max_daily_trades:
            logger.warning(
                f"📊 每日交易上限: {self.trades_today}/{self.max_daily_trades}"
            )
            return True
        return False

    # ═══════════════════════════════════════════════════════════════
    # Pre-order Check
    # ═══════════════════════════════════════════════════════════════

    def check_order(
        self,
        ticker: str,
        side: str,
        quantity: float,
        price: float,
    ) -> RiskReport:
        """Pre-trade risk check for a single order.

        Checks performed:
        1. Circuit breaker status
        2. Daily trade limit
        3. Sufficient cash (buys)
        4. Position concentration (buys)
        5. Max drawdown
        6. Minimum trade value

        Args:
            ticker: Stock ticker.
            side: ``"buy"`` or ``"sell"``.
            quantity: Number of shares.
            price: Limit / market price (USD).

        Returns:
            RiskReport — ``.passed`` is True only if all checks pass.
        """
        report = RiskReport()
        side_lower: str = side.lower().strip()

        # 1. Circuit breaker gate.
        if self.circuit_breaker_triggered:
            report.passed = False
            report.circuit_breaker = True
            report.reason = "🚨 熔断状态 — 拒绝所有新开仓"
            return report

        # 2. Daily trade limit.
        if self.check_daily_limit():
            report.passed = False
            report.daily_limit_reached = True
            report.reason = f"📊 日交易上限: {self.trades_today}/{self.max_daily_trades}"
            return report

        order_value: float = quantity * price

        # 3. Minimum trade value.
        if order_value < self.MIN_TRADE_VALUE:
            report.passed = False
            report.reason = (
                f"交易额不足: ${order_value:.2f} < ${self.MIN_TRADE_VALUE:.2f}"
            )
            return report

        # 4. Cash sufficiency (buy only).
        if side_lower == "buy":
            max_allowed: float = self.cash * self.MAX_CASH_USAGE
            if order_value > max_allowed:
                report.passed = False
                report.reason = (
                    f"🚫 资金不足 — 买入金额 ${order_value:,.2f} "
                    f"超过可用 $ {max_allowed:,.2f} "
                    f"(现金 ${self.cash:,.2f} × {self.MAX_CASH_USAGE:.0%})"
                )
                return report

        # 5. Position concentration (buy only).
        if side_lower == "buy":
            current_val: float = self.position_values.get(ticker, 0.0)
            total_val: float = current_val + order_value
            ratio: float = total_val / max(self.portfolio_value, 1.0)
            if ratio > self.MAX_POSITION_SIZE:
                report.passed = False
                report.reason = (
                    f"仓位超限: {ticker} 占比 {ratio:.1%} > {self.MAX_POSITION_SIZE:.0%}"
                )
                return report

        # 6. Max drawdown gate.
        if self.peak_value > self.portfolio_value:
            dd: float = (self.peak_value - self.portfolio_value) / self.peak_value
            if dd >= self.MAX_DRAWDOWN:
                report.passed = False
                report.reason = (
                    f"最大回撤触发: {dd:.1%} > {self.MAX_DRAWDOWN:.0%}"
                )
                return report

        report.details.update({
            "order_value": round(order_value, 2),
            "portfolio_value": round(self.portfolio_value, 2),
            "position_ratio": round(order_value / max(self.portfolio_value, 1.0), 4),
            "cash_remaining": round(self.cash, 2),
        })
        return report

    # ═══════════════════════════════════════════════════════════════
    # State Sync
    # ═══════════════════════════════════════════════════════════════

    def sync_portfolio_value(
        self,
        total_value: float,
        cash: Optional[float] = None,
        is_tiger_sync: bool = False,
    ) -> None:
        """Sync portfolio value from PortfolioManager / Tiger.

        On first call (daily_start_value == 0), initialises the
        daily-start and peak anchors from ``total_value``.

        When ``is_tiger_sync=True`` and this is the first Tiger sync
        (``_tiger_synced`` is False), the daily-start value is
        recalibrated from the real portfolio value to prevent a false
        circuit-breaker trigger caused by a stale initial-capital anchor.

        Args:
            total_value: Current portfolio total value (USD).
            cash: Current available cash (USD), optional.
            is_tiger_sync: True if called from Tiger account sync.
        """
        # ── First Tiger sync: recalibrate daily start ─────────
        if is_tiger_sync and not self._tiger_synced:
            self._tiger_synced = True
            self.portfolio_value = total_value
            self.daily_start_value = total_value
            self.peak_value = total_value
            if cash is not None:
                self.cash = cash
            logger.info(
                f"🔰 老虎首次同步校准: 资产 ${total_value:,.2f} → "
                f"daily_start / peak 已重置"
            )
            return

        if self.daily_start_value <= 0.0:
            logger.info(
                f"🔄 风控首次同步: 资产 ${self.portfolio_value:,.0f} → ${total_value:,.2f}"
            )
            self.portfolio_value = total_value
            self.daily_start_value = total_value
            self.peak_value = total_value
            if cash is not None:
                self.cash = cash
        else:
            self.portfolio_value = total_value
            if cash is not None:
                self.cash = cash

    def update_portfolio_state(
        self,
        portfolio_value: float,
        cash: float,
        positions: Dict[str, float],
        prices: Dict[str, float],
    ) -> None:
        """Full portfolio state update (per-cycle).

        Args:
            portfolio_value: Total value.
            cash: Available cash.
            positions: ticker → shares.
            prices: ticker → current price.
        """
        self.portfolio_value = portfolio_value
        self.cash = cash
        self.positions = dict(positions)
        self.position_values.clear()
        for ticker, shares in positions.items():
            px: float = prices.get(ticker, 0.0)
            if px > 0 and shares != 0.0:
                self.position_values[ticker] = shares * px
        self.peak_value = max(self.peak_value, portfolio_value)

    def reset_daily_state(self) -> None:
        """Reset state for a new trading day."""
        self.daily_start_value = self.portfolio_value
        self.circuit_breaker_triggered = False
        self.circuit_breaker_time = None
        self.trades_today = 0
        logger.info(
            f"📅 新交易日重置: 起始净值=${self.daily_start_value:,.2f}, "
            f"熔断状态=正常"
        )

    def record_trade(self) -> None:
        """Increment the daily trade counter."""
        self.trades_today += 1

    # ═══════════════════════════════════════════════════════════════
    # P1-3: Short-Position Auto-Fix
    # ═══════════════════════════════════════════════════════════════

    def fix_short_positions(
        self,
        portfolio: Any,
        tiger_bridge: Any,
        prices: Dict[str, float],
    ) -> int:
        """Detect and fix negative (short) positions.

        Iterates ``portfolio.positions``, finds any ticker with
        negative shares, and issues buy orders to close the short.

        Args:
            portfolio: ``shared.portfolio_manager.PortfolioManager`` instance.
            tiger_bridge: ``shared.tiger_bridge`` module reference.
            prices: ticker → current price (USD).

        Returns:
            Number of positions fixed.
        """
        fixed: int = 0
        for ticker, shares in list(portfolio.positions.items()):
            if shares >= 0.0:
                continue

            buy_qty: float = abs(shares)
            price: float = prices.get(ticker, 0.0)
            if price <= 0:
                logger.warning(f"⚠️ fix_short: {ticker} 无有效价格，跳过")
                continue

            logger.warning(
                f"🔧 修复空头: {ticker} | 本地 {shares:.2f} 股 → 买入 {buy_qty:.2f} 股"
            )

            # Attempt live fix via Tiger only in live mode.
            try:
                from shared.execution_mode import can_place_live_order

                if can_place_live_order(tiger_bridge):
                    tiger_bridge.place_order(
                        ticker=ticker,
                        action="BUY",
                        quantity=int(buy_qty),
                        order_type="MKT",
                    )
                    logger.info(f"  ✅ Tiger实盘修复 {ticker}: BUY {int(buy_qty)}")
                else:
                    logger.info(f"  📝 Paper修复 {ticker}: BUY {int(buy_qty)} (本地)")
            except Exception as exc:
                logger.error(f"  ❌ Tiger修复失败 {ticker}: {exc}")

            # Update local state.
            portfolio.execute_trade(
                ticker=ticker,
                side="buy",
                price=price,
                quantity=buy_qty,
                strategy="short_fix",
            )
            fixed += 1

        if fixed > 0:
            logger.info(f"✅ 空头修复完成: {fixed} 只")
        return fixed

    # ═══════════════════════════════════════════════════════════════
    # Status & Admin
    # ═══════════════════════════════════════════════════════════════

    def get_status(self) -> Dict[str, Any]:
        """Return a human-readable risk status snapshot."""
        daily_pnl: float = 0.0
        daily_pnl_pct: float = 0.0
        if self.daily_start_value > 0:
            daily_pnl = self.portfolio_value - self.daily_start_value
            daily_pnl_pct = daily_pnl / self.daily_start_value

        current_dd: float = 0.0
        if self.peak_value > 0:
            current_dd = (self.peak_value - self.portfolio_value) / self.peak_value

        return {
            "portfolio_value": round(self.portfolio_value, 2),
            "cash": round(self.cash, 2),
            "peak_value": round(self.peak_value, 2),
            "daily_start_value": round(self.daily_start_value, 2),
            "daily_pnl": round(daily_pnl, 2),
            "daily_pnl_pct": round(daily_pnl_pct, 4),
            "current_drawdown": round(current_dd, 4),
            "circuit_breaker_triggered": self.circuit_breaker_triggered,
            "breaker_mode": self.breaker_mode,
            "trades_today": self.trades_today,
            "max_daily_trades": self.max_daily_trades,
            "num_positions": sum(1 for s in self.positions.values() if s != 0),
        }

    def force_reset_circuit(self) -> None:
        """Force-reset the circuit breaker (e.g. from dashboard)."""
        self.circuit_breaker_triggered = False
        self.circuit_breaker_time = None
        self.peak_value = max(self.peak_value, self.portfolio_value)
        logger.info(f"🔄 断路器已重置，峰值校准至 ${self.peak_value:,.2f}")

    def toggle_breaker_mode(self, mode: str) -> None:
        """Switch breaker mode.

        Args:
            mode: ``"hard"`` (block + liquidate) or ``"warn"`` (log only).

        Raises:
            ValueError: If mode is not ``"hard"`` or ``"warn"``.
        """
        if mode not in ("hard", "warn"):
            raise ValueError(
                f"Invalid breaker mode: {mode!r}. Must be 'hard' or 'warn'."
            )
        old: str = self.breaker_mode
        self.breaker_mode = mode
        logger.info(f"🔧 断路器模式切换: {old} → {mode}")
