"""
Risk system — institutional-grade controls.
- VaR (Value at Risk)
- Max-drawdown control
- Position limits
- Stop-loss / take-profit
- Correlation risk
- Liquidity risk
- P0-2: Portfolio circuit breaker
"""
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, field
import numpy as np
from loguru import logger

from configs.settings import settings


@dataclass
class RiskReport:
    """Risk report."""
    passed: bool = True
    total_risk_score: float = 0.0
    violations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    circuit_breaker: bool = False
    details: Dict = field(default_factory=dict)


class RiskManager:
    """
    Unified risk manager.
    Multi-layer pre-trade checks.

    P0-2: Portfolio circuit breaker
    - Daily loss ≥ DAILY_LOSS_LIMIT (5%) → trip breaker
    - Drawdown ≥ MAX_DRAWDOWN (25%) → trip breaker
    - After trip: liquidate all positions and halt new trades
    """

    def __init__(self):
        self.portfolio_value = settings.TRADING_INITIAL_CAPITAL
        self.cash = settings.TRADING_INITIAL_CAPITAL
        self.positions: Dict[str, float] = {}  # ticker -> shares
        self.position_values: Dict[str, float] = {}  # ticker -> market value
        self.trade_history: List[Dict] = []
        self.price_history: Dict[str, List[float]] = {}
        self.peak_value = settings.TRADING_INITIAL_CAPITAL

        # P0-2: Circuit-breaker state
        self.daily_start_value: float = settings.TRADING_INITIAL_CAPITAL
        self.circuit_breaker_triggered: bool = False
        self.circuit_breaker_time: Optional[datetime] = None

        # P0-3: Breaker mode — "hard" = trip + liquidate, "warn" = log-only
        self.breaker_mode: str = "hard"

        # Skip extreme DD anomaly only before broker sync completes
        self._tiger_synced: bool = False

    # ================================================================
    # P0-2: Portfolio circuit breaker
    # ================================================================

    def check_circuit_breaker(self) -> RiskReport:
        """
        Portfolio circuit-breaker check (called each trading cycle).

        Logic:
        1. Daily loss ≥ DAILY_LOSS_LIMIT (default 5%) → trip
        2. Max drawdown ≥ MAX_DRAWDOWN (default 25%) → trip
        3. Already in cooldown → keep tripped

        P0-3: breaker_mode
        - "hard" = trip and liquidate all positions
        - "warn" = log-only, do not block trading

        Returns:
            RiskReport with circuit_breaker flag
        """
        report = RiskReport()
        is_warn_mode = self.breaker_mode == "warn"

        # Check whether cooldown has elapsed
        if self.circuit_breaker_triggered and self.circuit_breaker_time is not None:
            cooldown_seconds = (datetime.now() - self.circuit_breaker_time).total_seconds()
            if cooldown_seconds < settings.TRADING_CIRCUIT_BREAKER_COOLDOWN:
                report.circuit_breaker = True
                report.passed = False
                report.violations.append(
                    f"🚨 Breaker cooldown: {cooldown_seconds:.0f}s / "
                    f"{settings.TRADING_CIRCUIT_BREAKER_COOLDOWN}s remaining"
                )
                report.details["breaker_mode"] = self.breaker_mode
                return report
            else:
                # Cooldown ended; auto-clear the breaker
                logger.info("🟢 Breaker cooldown ended; trading resumed")
                self.circuit_breaker_triggered = False
                self.circuit_breaker_time = None

        # Daily-loss check
        daily_pnl = self.get_daily_pnl()
        daily_pnl_pct = daily_pnl / (self.daily_start_value + 1e-8)

        if daily_pnl_pct <= -settings.TRADING_DAILY_LOSS_LIMIT:
            report.circuit_breaker = True
            report.passed = False
            if is_warn_mode:
                report.violations.append(
                    f"⚠️ Breaker warning (not blocking): daily loss {daily_pnl_pct:.2%} ≥ "
                    f"limit {settings.TRADING_DAILY_LOSS_LIMIT:.0%}"
                )
                logger.warning(
                    f"⚠️ Breaker warning (warn mode, not blocking): daily PnL={daily_pnl_pct:.2%}, "
                    f"NAV=${self.portfolio_value:,.0f}, start=${self.daily_start_value:,.0f}"
                )
            else:
                report.violations.append(
                    f"🚨 Circuit breaker tripped! Daily loss {daily_pnl_pct:.2%} ≥ "
                    f"limit {settings.TRADING_DAILY_LOSS_LIMIT:.0%}"
                )
                self.circuit_breaker_triggered = True
                self.circuit_breaker_time = datetime.now()
                logger.error(
                    f"🚨 Circuit breaker tripped! Daily PnL={daily_pnl_pct:.2%}, "
                    f"NAV=${self.portfolio_value:,.0f}, start=${self.daily_start_value:,.0f}"
                )

        # Max-drawdown check
        current_dd = self.get_current_drawdown()
        # Extreme DD (>90%) is treated as data noise ONLY before broker sync.
        anomaly_skip = current_dd >= 0.90 and not self._tiger_synced
        if (self.peak_value > self.portfolio_value
                and self.portfolio_value > 0
                and not anomaly_skip):
            if current_dd >= settings.TRADING_MAX_DRAWDOWN:
                report.circuit_breaker = True
                report.passed = False
                if is_warn_mode:
                    report.violations.append(
                        f"⚠️ Breaker warning (not blocking): max drawdown {current_dd:.2%} ≥ "
                        f"limit {settings.TRADING_MAX_DRAWDOWN:.0%}"
                    )
                    logger.warning(
                        f"⚠️ Breaker warning (warn mode, not blocking): drawdown={current_dd:.2%}"
                    )
                else:
                    report.violations.append(
                        f"🚨 Circuit breaker tripped! Max drawdown {current_dd:.2%} ≥ "
                        f"limit {settings.TRADING_MAX_DRAWDOWN:.0%}"
                    )
                    self.circuit_breaker_triggered = True
                    self.circuit_breaker_time = datetime.now()
                    logger.error(f"🚨 Circuit breaker tripped! Drawdown={current_dd:.2%}")
        elif anomaly_skip and self.portfolio_value > 0:
            logger.warning(
                f"⚠️ Anomalous drawdown {current_dd:.2%} before data sync completed; "
                f"skipping breaker (peak=${self.peak_value:,.0f}, pv=${self.portfolio_value:,.0f})"
            )

        if report.circuit_breaker:
            report.total_risk_score = 1.0

        report.details["daily_pnl_pct"] = daily_pnl_pct
        report.details["daily_start_value"] = self.daily_start_value
        report.details["current_drawdown"] = current_dd
        report.details["breaker_mode"] = self.breaker_mode

        return report

    def liquidate_all(self, prices: Dict[str, float]) -> List[Dict]:
        """
        P0-2: Liquidate all positions after a breaker trip.

        Args:
            prices: {ticker: current_price} used to value the close-out

        Returns:
            Liquidation records, each with ticker, shares, price, value
        """
        if not self.positions:
            logger.info("📭 No positions to liquidate")
            return []

        logger.warning(f"🚨 Portfolio liquidation: {len(self.positions)} positions")
        liquidation_records = []

        for ticker, shares in list(self.positions.items()):
            if shares <= 0:
                continue

            price = prices.get(ticker, 0.0)
            if price <= 0:
                logger.warning(f"⚠️ {ticker} has no valid price; skip liquidation")
                continue

            value = shares * price
            self.cash += value
            self.position_values.pop(ticker, None)
            self.positions[ticker] = 0.0

            record = {
                "ticker": ticker,
                "side": "sell",
                "shares": shares,
                "price": price,
                "value": value,
                "reason": "circuit_breaker_liquidation",
                "timestamp": datetime.now().isoformat(),
            }
            liquidation_records.append(record)
            logger.info(
                f"  📉 Liquidate {ticker}: {shares:.0f} sh @ ${price:.2f} = ${value:,.2f}"
            )

        # Update portfolio value
        if self.positions:
            remaining_value = sum(
                self.positions.get(t, 0) * prices.get(t, 0)
                for t in self.positions
            )
        else:
            remaining_value = 0.0
        self.portfolio_value = self.cash + remaining_value

        logger.warning(
            f"✅ Liquidation complete: {len(liquidation_records)} fills, "
            f"cash ${self.cash:,.2f}, NAV ${self.portfolio_value:,.2f}"
        )

        return liquidation_records

    def force_reset_circuit(self):
        """
        P0-3: Force-reset the circuit breaker and recalibrate peak value.

        Used by the dashboard reset button or an automated recovery flow.
        After reset the breaker is clear and peak is set to current NAV.
        """
        self.circuit_breaker_triggered = False
        self.circuit_breaker_time = None
        self.peak_value = max(self.peak_value, self.portfolio_value)
        logger.info(f"🔄 Circuit breaker reset; peak calibrated to ${self.peak_value:,.2f}")

    def toggle_breaker_mode(self, mode: str):
        """
        P0-3: Toggle circuit-breaker mode.

        Args:
            mode: "hard" = trip + liquidate, "warn" = log-only
        """
        if mode not in ("hard", "warn"):
            logger.error(f"❌ Invalid breaker mode: {mode}; only 'hard' or 'warn'")
            raise ValueError(f"Invalid breaker mode: {mode}. Must be 'hard' or 'warn'.")
        old_mode = self.breaker_mode
        self.breaker_mode = mode
        logger.info(f"🔧 Breaker mode switched: {old_mode} → {mode}")

    def sync_portfolio_value(self, total_value: float, cash: float = None):
        """
        Sync actual portfolio value from Tiger/Portfolio into risk.
        Avoids false loss alarms when INITIAL_CAPITAL does not match the live account.

        First call calibrates daily_start_value and peak_value;
        later calls only update portfolio_value (used by the breaker).
        """
        is_first_sync = (self.portfolio_value == settings.TRADING_INITIAL_CAPITAL
                         and self.daily_start_value == settings.TRADING_INITIAL_CAPITAL)

        if is_first_sync:
            logger.info(
                f"🔄 Risk first sync: NAV ${self.portfolio_value:,.0f} → ${total_value:,.2f}"
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

    def reset_daily_state(self):
        """
        P0-2: Reset breaker state and daily start NAV for a new session.
        Call at the start of each trading day.
        """
        self.daily_start_value = self.portfolio_value
        self.circuit_breaker_triggered = False
        self.circuit_breaker_time = None
        logger.info(
            f"📅 New session reset: start NAV=${self.daily_start_value:,.2f}, "
            f"breaker=clear"
        )

    # ================================================================
    # Main risk check
    # ================================================================

    def check_order(
        self,
        ticker: str,
        side: str,
        quantity: float,
        price: float,
    ) -> RiskReport:
        """
        Pre-trade risk check.

        Args:
            ticker: Symbol
            side: buy/sell
            quantity: Shares
            price: Limit price

        Returns:
            RiskReport
        """
        report = RiskReport()

        # P0-2: Reject all new entries while the breaker is tripped
        if self.circuit_breaker_triggered:
            report.passed = False
            report.circuit_breaker = True
            report.violations.append("🚨 Circuit breaker — rejecting all new entries")
            return report

        order_value = quantity * price

        # 1. Cash check
        if side == "buy":
            cash_check = self._check_sufficient_cash(order_value)
            if not cash_check["passed"]:
                report.violations.append(cash_check["reason"])
                report.passed = False

        # 2. Concentration check
        if side == "buy":
            concentration = self._check_position_concentration(ticker, order_value)
            if not concentration["passed"]:
                report.violations.append(concentration["reason"])
                report.passed = False

        # 3. Max-drawdown check
        dd_check = self._check_max_drawdown()
        if not dd_check["passed"]:
            report.violations.append(dd_check["reason"])
            report.passed = False

        # 4. VaR check
        var_check = self._check_var(ticker, order_value)
        if not var_check["passed"]:
            report.warnings.append(var_check["reason"])
            report.total_risk_score += 0.3

        # 5. Liquidity check
        liq_check = self._check_liquidity(ticker, order_value)
        if not liq_check["passed"]:
            report.warnings.append(liq_check["reason"])

        # 6. Stop-loss check
        if side == "sell":
            sl_check = self._check_stop_loss(ticker, price)
            if sl_check["triggered"]:
                report.details["stop_loss_triggered"] = True

        # Aggregate risk score
        report.total_risk_score = len(report.violations) * 0.5 + len(report.warnings) * 0.2
        report.details.update({
            "order_value": order_value,
            "portfolio_value": self.portfolio_value,
            "position_ratio": order_value / (self.portfolio_value + 1e-8),
            "cash_remaining": self.cash,
        })

        return report

    def update_portfolio_state(
        self,
        portfolio_value: float,
        cash: float,
        positions: Dict[str, float],
        prices: Dict[str, float],
    ):
        """Update portfolio state (called every tick)."""
        self.portfolio_value = portfolio_value
        self.cash = cash
        self.positions = positions

        # Update position market values
        for ticker, shares in positions.items():
            if ticker in prices:
                self.position_values[ticker] = shares * prices[ticker]

        # Update price history
        for ticker, price in prices.items():
            if ticker not in self.price_history:
                self.price_history[ticker] = []
            self.price_history[ticker].append(price)
            # Keep last 252 days
            if len(self.price_history[ticker]) > 252:
                self.price_history[ticker] = self.price_history[ticker][-252:]

        # Update peak
        self.peak_value = max(self.peak_value, portfolio_value)

    def get_current_drawdown(self) -> float:
        """Return current drawdown."""
        if self.peak_value == 0:
            return 0.0
        return (self.peak_value - self.portfolio_value) / self.peak_value

    def get_daily_pnl(self) -> float:
        """
        P0-2: Daily P&L versus session-start NAV.

        Returns:
            Daily P&L amount (signed)
        """
        return self.portfolio_value - self.daily_start_value

    # ================================================================
    # Internal risk checks
    # ================================================================

    def _check_sufficient_cash(self, order_value: float) -> Dict:
        """Cash check — never use leverage."""
        from configs.settings import settings as tcfg
        max_allowed = self.cash * tcfg.MAX_CASH_USAGE
        if order_value > max_allowed:
            return {
                "passed": False,
                "reason": (
                    f"🚫 No-leverage rule — buy notional ${order_value:,.2f} "
                    f"exceeds available cash ${max_allowed:,.2f} "
                    f"(cash ${self.cash:,.2f} × {tcfg.MAX_CASH_USAGE:.0%}) — "
                    f"leverage is never used"
                )
            }
        return {"passed": True}

    def _check_position_concentration(self, ticker: str, add_value: float) -> Dict:
        """Position concentration check."""
        # Current position MV + incremental
        current_position_value = self.position_values.get(ticker, 0.0)
        total_position_value = current_position_value + add_value
        position_ratio = total_position_value / (self.portfolio_value + 1e-8)

        if position_ratio > settings.TRADING_MAX_POSITION_SIZE:
            return {
                "passed": False,
                "reason": f"Position limit: {ticker} weight {position_ratio:.1%} > {settings.TRADING_MAX_POSITION_SIZE:.0%}"
            }
        return {"passed": True}

    def _check_max_drawdown(self) -> Dict:
        """Max-drawdown check."""
        dd = self.get_current_drawdown()
        if dd > settings.TRADING_MAX_DRAWDOWN:
            return {
                "passed": False,
                "reason": f"Max drawdown tripped: {dd:.1%} > {settings.TRADING_MAX_DRAWDOWN:.0%}"
            }
        return {"passed": True}

    def _check_var(self, ticker: str, order_value: float) -> Dict:
        """VaR check."""
        if ticker not in self.price_history or len(self.price_history[ticker]) < 20:
            return {"passed": True}

        returns = np.diff(self.price_history[ticker]) / (np.array(self.price_history[ticker][:-1]) + 1e-8)
        var = np.percentile(returns, (1 - settings.TRADING_VAR_CONFIDENCE) * 100)
        potential_loss = abs(var * order_value)

        risk_threshold = self.portfolio_value * settings.TRADING_MAX_PORTFOLIO_RISK
        if potential_loss > risk_threshold:
            return {
                "passed": False,
                "reason": f"VaR breach: potential loss ${potential_loss:.2f} > ${risk_threshold:.2f}"
            }
        return {"passed": True}

    def _check_liquidity(self, ticker: str, order_value: float) -> Dict:
        """Liquidity check (simplified)."""
        # Production would query average daily volume
        return {"passed": True}

    def _check_stop_loss(self, ticker: str, current_price: float) -> Dict:
        """Stop-loss check."""
        avg_cost = self._get_avg_cost(ticker)
        if avg_cost <= 0:
            return {"triggered": False}

        loss_pct = (current_price - avg_cost) / avg_cost

        if loss_pct <= -settings.TRADING_STOP_LOSS_PCT:
            logger.warning(f"⚠️ {ticker} stop-loss: {loss_pct:.1%} ≤ {settings.TRADING_STOP_LOSS_PCT:.0%}")
            return {"triggered": True, "loss_pct": loss_pct}

        return {"triggered": False}

    def _get_avg_cost(self, ticker: str) -> float:
        """Return average cost basis."""
        buy_trades = [t for t in self.trade_history
                      if t["ticker"] == ticker and t["side"] == "buy"]
        if not buy_trades:
            return 0.0

        total_cost = sum(t["value"] for t in buy_trades)
        total_shares = sum(t["quantity"] for t in buy_trades)
        return total_cost / (total_shares + 1e-8)

    def get_status(self) -> Dict:
        """Return risk status."""
        return {
            "max_drawdown": round(self.get_current_drawdown(), 4),
            "peak_value": round(self.peak_value, 2),
            "daily_pnl": round(self.get_daily_pnl(), 2),
            "daily_pnl_pct": round(self.get_daily_pnl() / (self.daily_start_value + 1e-8), 4),
            "circuit_breaker_triggered": self.circuit_breaker_triggered,
            "breaker_mode": self.breaker_mode,
            "daily_start_value": round(self.daily_start_value, 2),
            "var_95": 0.0,  # Simplified
            "position_concentration": {
                t: round(v / (self.portfolio_value + 1e-8), 4)
                for t, v in self.position_values.items()
            },
        }
