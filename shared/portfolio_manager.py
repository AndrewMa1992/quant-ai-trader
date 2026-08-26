"""
PortfolioManager — v2 portfolio state manager
==============================================
Replaces ``backend.trading_engine.portfolio.PortfolioManager``.
Data-model independent — no direct ``import backend.``.

Tracks positions, cash, average costs, and computes portfolio-level
metrics. Syncs with Tiger via the shared tiger_bridge module.
State persistence uses JSON format at ``data/portfolio_state.json``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from loguru import logger


@dataclass
class PositionRecord:
    """Single-position data container."""

    ticker: str
    shares: float
    avg_cost: float = 0.0


class PortfolioManager:
    """Investment portfolio state manager.

    Maintains the local mirror of positions, cash, and average costs.

    In **live** mode Tiger is authoritative. In **paper/simulation** mode the
    local book (``QAT_TRADING_INITIAL_CAPITAL``) is authoritative when the Tiger
    paper account reports ~zero NAV/cash — an unfunded paper account must not
    wipe local buying power and silently kill US orders.

    Attributes:
        initial_capital: Starting capital (USD).
        cash: Available cash (USD).
        positions: ticker → shares mapping.
        avg_costs: ticker → average cost per share (USD).
        total_value: Total portfolio value (cash + positions market value).
    """

    # Treat Tiger cash/NAV at or below this as "empty / unfunded paper".
    _ZERO_NAV_EPS: float = 1.0

    def __init__(self, initial_capital: float = 100000.0) -> None:
        self.initial_capital: float = initial_capital
        self.cash: float = initial_capital
        self.positions: Dict[str, float] = {}  # ticker → shares
        self.avg_costs: Dict[str, float] = {}  # ticker → avg cost (USD)
        self.total_value: float = initial_capital

        # Internal cache of last-seen prices (populated by update_value).
        self._last_prices: Dict[str, float] = {}

        # History for metrics.
        self._value_history: List[float] = [initial_capital]
        self._daily_returns: List[float] = []
        self._trade_history: List[Dict[str, Any]] = []

        # Tiger sync flag.
        self._tiger_initial_capital_synced: bool = False

    # ═══════════════════════════════════════════════════════════════
    # Tiger Sync
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _is_paper_or_sim_mode() -> bool:
        """True when we must protect local capital from an empty Tiger paper book."""
        try:
            from shared.execution_mode import is_simulation_mode, get_execution_mode

            if is_simulation_mode():
                return True
            if get_execution_mode() == "paper":
                return True
        except Exception:
            pass
        try:
            from configs.settings import settings

            if bool(getattr(settings, "TIGER_PAPER_TRADING", False)):
                return True
        except Exception:
            pass
        # Default safe: treat as paper when env is unset
        raw = os.getenv("QAT_TRADING_SIMULATION_MODE", "true").strip().lower()
        return raw in ("1", "true", "yes", "on", "")

    def ensure_buying_power(self, floor: Optional[float] = None) -> bool:
        """Restore cash/NAV when a prior Tiger zero-sync wiped the local book.

        Returns:
            True if capital was restored.
        """
        if not self._is_paper_or_sim_mode():
            return False
        target = float(floor if floor is not None else self.initial_capital)
        if target <= self._ZERO_NAV_EPS:
            try:
                from configs.settings import settings

                target = float(getattr(settings, "TRADING_INITIAL_CAPITAL", 1700.0))
            except Exception:
                target = 1700.0
        if self.cash > self._ZERO_NAV_EPS or self.total_value > self._ZERO_NAV_EPS:
            return False
        logger.warning(
            f"💰 Restoring wiped paper capital: cash/NAV≈0 → "
            f"${target:,.2f} (Tiger paper likely unfunded)"
        )
        self.initial_capital = target
        self.cash = target
        self.total_value = target
        self._tiger_initial_capital_synced = False
        if not self._value_history:
            self._value_history = [target]
        else:
            self._value_history.append(target)
        self.save_state()
        return True

    def sync_from_tiger(
        self,
        tiger_bridge: Any,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Pull positions and account info from Tiger, overwriting local state.

        The tiger_bridge parameter is the ``shared.tiger_bridge`` module
        (or a compatible object exposing the same function signatures).

        In paper/sim mode, an empty Tiger paper account (cash≈0 and NAV≈0)
        does **not** overwrite local capital — that was wiping $1700 → $0 and
        preventing all US order sizing.

        Args:
            tiger_bridge: Tiger bridge module (shared.tiger_bridge).
            force: If True, force re-sync even when already synced.

        Returns:
            Dict with keys: ``synced``, ``positions``, ``cash``,
            ``total_value``, ``source``.
        """
        result: Dict[str, Any] = {
            "synced": False,
            "positions": 0,
            "cash": 0.0,
            "total_value": 0.0,
            "source": "none",
        }

        try:
            # Check / establish connection.
            if not tiger_bridge.is_connected():
                logger.info("🔄 Tiger not connected, attempting reconnect...")
                tiger_bridge.connect()

            if not tiger_bridge.is_connected():
                logger.warning("⚠️ Tiger offline — cannot sync positions")
                result["source"] = "tiger_offline"
                return result

            # Force re-connect to ensure session freshness.
            tiger_bridge.connect()

            # Pull data from Tiger.
            tiger_positions: List[Dict[str, Any]] = tiger_bridge.get_positions(force=True)
            tiger_account: Optional[Dict[str, Any]] = tiger_bridge.get_account_info(force=True)

            if not tiger_account:
                logger.warning("⚠️ Cannot retrieve Tiger account info")
                result["source"] = "tiger_account_error"
                return result

            tiger_cash: float = float(tiger_account.get("cash", 0.0) or 0.0)
            tiger_total: float = float(tiger_account.get("total_value", 0.0) or 0.0)
            tiger_pos_count: int = len(tiger_positions or [])

            # Safety net: Tiger returned 0 positions but we have many locally.
            old_pos_count: int = len(self.positions)
            if tiger_pos_count == 0 and old_pos_count > 5:
                logger.error(
                    f"🚨 Tiger returned 0 positions but local has {old_pos_count}! "
                    f"Tiger API may be anomalous — preserving local data"
                )
                result["synced"] = False
                result["source"] = "tiger_empty_abnormal"
                result["positions"] = old_pos_count
                result["cash"] = self.cash
                result["total_value"] = self.total_value
                return result

            # Critical: unfunded Tiger paper (NAV/cash≈0) must not wipe local book.
            # Otherwise rebalance sizes off total_value≈0 → zero US orders forever.
            local_nav = max(float(self.total_value), float(self.cash), float(self.initial_capital))
            tiger_empty = (
                tiger_cash <= self._ZERO_NAV_EPS
                and tiger_total <= self._ZERO_NAV_EPS
                and tiger_pos_count == 0
            )
            if (
                tiger_empty
                and self._is_paper_or_sim_mode()
                and local_nav > self._ZERO_NAV_EPS
                and not force
            ):
                logger.warning(
                    f"🛡️ Tiger paper empty (cash=${tiger_cash:,.2f}, NAV=${tiger_total:,.2f}) "
                    f"— keeping local capital ${local_nav:,.2f}. "
                    f"Fund/reset Tiger paper if you need broker-side fills."
                )
                result["synced"] = False
                result["source"] = "tiger_zero_nav_preserved"
                result["positions"] = old_pos_count
                result["cash"] = self.cash
                result["total_value"] = self.total_value
                result["tiger_cash"] = tiger_cash
                result["tiger_total"] = tiger_total
                return result

            # Overwrite local state from Tiger.
            self.positions.clear()
            self.avg_costs.clear()
            self.cash = tiger_cash

            # ── initial_capital anchoring ──────────────────────
            if tiger_total > 0:
                need_reset: bool = (
                    force
                    or not self._tiger_initial_capital_synced
                    or abs(tiger_total - self.initial_capital)
                    / max(self.initial_capital, 1.0)
                    > 0.05
                )
                if need_reset:
                    reason: str = (
                        "强制重置" if force
                        else "首次同步" if not self._tiger_initial_capital_synced
                        else f"差距 {abs(tiger_total - self.initial_capital) / max(self.initial_capital, 1) * 100:.1f}%"
                    )
                    logger.info(
                        f"🔑 Tiger sync initial_capital ({reason}): "
                        f"${self.initial_capital:,.2f} → ${tiger_total:,.2f}"
                    )
                    self.initial_capital = tiger_total
                    self._tiger_initial_capital_synced = True
                    self._value_history = [tiger_total]

            # Load positions.
            for pos in tiger_positions:
                ticker: str = pos.get("ticker", "")
                shares: float = float(
                    pos.get("shares")
                    if pos.get("shares") is not None
                    else pos.get("quantity", 0.0)
                )
                avg_cost: float = float(pos.get("avg_cost", 0.0))
                if ticker and shares != 0.0:
                    self.positions[ticker] = shares
                    self.avg_costs[ticker] = avg_cost
                    mv = float(pos.get("market_value") or 0.0)
                    if mv > 0 and abs(shares) > 0:
                        self._last_prices[ticker] = mv / abs(shares)

            # Compute total_value — Tiger's is authoritative when positive.
            if tiger_total > 0:
                self.total_value = tiger_total
            else:
                positions_value: float = sum(
                    float(pos.get("market_value", 0.0)) for pos in tiger_positions
                )
                self.total_value = self.cash + positions_value

            # If force-synced an empty Tiger into a paper book, restore floor.
            if tiger_empty and self._is_paper_or_sim_mode():
                self.ensure_buying_power(local_nav if local_nav > self._ZERO_NAV_EPS else None)

            # Result.
            pos_count: int = sum(1 for s in self.positions.values() if s > 0)
            neg_count: int = sum(1 for s in self.positions.values() if s < 0)
            result["synced"] = True
            result["positions"] = pos_count
            result["negative_positions"] = neg_count
            result["cash"] = self.cash
            result["total_value"] = self.total_value
            result["source"] = "tiger_api"

            logger.info(
                f"🔄 Tiger sync complete: "
                f"{pos_count} positions, "
                f"cash ${self.cash:,.2f}, "
                f"total ${self.total_value:,.2f}"
            )

            if neg_count > 0:
                neg_list = [(t, s) for t, s in self.positions.items() if s < 0]
                neg_tickers = [t for t, _ in neg_list[:10]]
                logger.warning(f"⚠️ Found {neg_count} negative positions (short): {neg_tickers}")
                result["negative_tickers"] = neg_tickers

            # Leverage check.
            tiger_leverage: float = float(tiger_account.get("leverage", 1.0))
            if tiger_leverage > 1.001:
                tiger_mkt: float = float(tiger_account.get("market_value", 0.0))
                margin_amt: float = (
                    tiger_mkt - tiger_total
                    if tiger_mkt > tiger_total
                    else (tiger_leverage - 1.0) * tiger_total
                )
                result["margin_detected"] = True
                result["margin_amount"] = round(margin_amt, 2)
                result["leverage"] = round(tiger_leverage, 4)
                logger.warning(
                    f"⚠️ Tiger leverage detected! ratio={tiger_leverage:.4f} | "
                    f"mkt ${tiger_mkt:,.0f} | nav ${tiger_total:,.0f}"
                )
            else:
                result["margin_detected"] = False

            # Persist after sync.
            self.save_state()
            logger.info("  📝 Tiger sync state saved to local JSON")

            return result

        except Exception as exc:
            logger.error(f"❌ Tiger sync failed: {exc}", exc_info=True)
            result["source"] = "sync_error"
            return result

    # ═══════════════════════════════════════════════════════════════
    # Trade Execution
    # ═══════════════════════════════════════════════════════════════

    def execute_trade(
        self,
        ticker: str,
        side: str,
        price: float,
        quantity: float,
        strategy: str = "rebalance",
    ) -> Optional[Dict[str, Any]]:
        """Execute a trade and update local state.

        Args:
            ticker: Ticker symbol (e.g. ``"AAPL"``).
            side: ``"BUY"`` or ``"SELL"``.
            price: Execution price per share (USD).
            quantity: Number of shares.
            strategy: Trade strategy label for record-keeping.

        Returns:
            Trade record dict, or None if the trade could not be executed.
        """
        side_lower: str = side.lower().strip()
        if side_lower not in ("buy", "sell"):
            logger.warning(f"PortfolioManager: invalid side '{side}' for {ticker}")
            return None

        if quantity <= 0.0 or price <= 0.0:
            logger.warning(
                f"PortfolioManager: invalid params for {ticker} "
                f"(price={price}, qty={quantity})"
            )
            return None

        if side_lower == "buy":
            return self._execute_buy(ticker, price, quantity, strategy)
        return self._execute_sell(ticker, price, quantity, strategy)

    def _execute_buy(
        self, ticker: str, price: float, quantity: float, strategy: str
    ) -> Optional[Dict[str, Any]]:
        """Execute a buy order."""
        cost: float = price * quantity

        if cost > self.cash:
            logger.warning(
                f"🚫 Insufficient cash for {ticker} buy: "
                f"need ${cost:,.2f} > available ${self.cash:,.2f}"
            )
            return None

        # Update positions and avg cost.
        old_shares: float = self.positions.get(ticker, 0.0)
        old_cost: float = self.avg_costs.get(ticker, 0.0)

        new_shares: float = old_shares + quantity
        if new_shares > 0:
            self.avg_costs[ticker] = (
                old_cost * old_shares + price * quantity
            ) / new_shares

        self.positions[ticker] = new_shares
        self.cash -= cost

        record: Dict[str, Any] = {
            "ticker": ticker,
            "side": "buy",
            "quantity": round(quantity, 4),
            "price": round(price, 2),
            "value": round(cost, 2),
            "strategy": strategy,
            "timestamp": datetime.now().isoformat(),
        }
        self._trade_history.append(record)

        logger.info(
            f"📈 BUY  {ticker}: {quantity:.2f} sh @ ${price:.2f} = ${cost:.2f}"
        )
        return record

    def _execute_sell(
        self, ticker: str, price: float, quantity: float, strategy: str
    ) -> Optional[Dict[str, Any]]:
        """Execute a sell order."""
        shares: float = self.positions.get(ticker, 0.0)

        if shares <= 0.0:
            logger.warning(f"Cannot sell {ticker}: no position")
            return None

        # Cap quantity at current position.
        actual_qty: float = min(quantity, shares)
        proceeds: float = price * actual_qty

        self.cash += proceeds
        new_shares: float = shares - actual_qty
        if new_shares < 0.001:
            self.positions.pop(ticker, None)
            self.avg_costs.pop(ticker, None)
            self._last_prices.pop(ticker, None)
        else:
            self.positions[ticker] = new_shares

        record: Dict[str, Any] = {
            "ticker": ticker,
            "side": "sell",
            "quantity": round(actual_qty, 4),
            "price": round(price, 2),
            "value": round(proceeds, 2),
            "strategy": strategy,
            "timestamp": datetime.now().isoformat(),
        }
        self._trade_history.append(record)

        logger.info(
            f"📉 SELL {ticker}: {actual_qty:.2f} sh @ ${price:.2f} = ${proceeds:.2f}"
        )
        return record

    # ═══════════════════════════════════════════════════════════════
    # Valuation
    # ═══════════════════════════════════════════════════════════════

    def update_value(self, prices: Dict[str, float]) -> None:
        """Update portfolio total value from latest prices.

        Args:
            prices: ticker → price (USD) mapping.
        """
        positions_value: float = 0.0
        for ticker, shares in self.positions.items():
            px: float = prices.get(ticker, self._last_prices.get(ticker, 0.0))
            if px > 0:
                positions_value += shares * px
                self._last_prices[ticker] = px

        prev_value: float = self.total_value
        self.total_value = self.cash + positions_value
        self._value_history.append(self.total_value)

        # Daily return.
        if prev_value > 0:
            daily_ret: float = (self.total_value - prev_value) / prev_value
            self._daily_returns.append(daily_ret)

    def get_positions_summary(self) -> Dict[str, Dict[str, float]]:
        """Return a summary of current positions.

        Returns:
            Dict mapping ticker → {
                ``shares``, ``avg_cost``, ``current_value``, ``pnl_pct``
            }.
        """
        summary: Dict[str, Dict[str, float]] = {}
        for ticker, shares in self.positions.items():
            avg_cost: float = self.avg_costs.get(ticker, 0.0)
            current_px: float = self._last_prices.get(ticker, avg_cost)
            current_value: float = shares * current_px
            pnl_pct: float = 0.0
            if avg_cost > 0 and current_px > 0:
                pnl_pct = (current_px / avg_cost - 1.0) * 100.0

            summary[ticker] = {
                "shares": round(shares, 4),
                "avg_cost": round(avg_cost, 2),
                "current_value": round(current_value, 2),
                "pnl_pct": round(pnl_pct, 2),
            }
        return summary

    def get_metrics(self) -> Dict[str, Any]:
        """Compute portfolio-level metrics.

        Returns:
            Dict with keys: ``total_value``, ``cash``, ``num_positions``,
            ``daily_pnl``, ``total_return_pct``, ``sharpe_ratio``,
            ``max_drawdown``, ``total_trades``.
        """
        returns: np.ndarray = (
            np.array(self._daily_returns)
            if self._daily_returns
            else np.array([0.0])
        )

        sharpe: float = 0.0
        if len(returns) >= 5 and returns.std() > 0:
            sharpe = float((returns.mean() / returns.std()) * np.sqrt(252))

        total_pnl: float = self.total_value - self.initial_capital
        total_return_pct: float = (
            (self.total_value / max(self.initial_capital, 1.0) - 1.0)
            * 100.0
        )

        # Max drawdown.
        max_dd: float = 0.0
        if len(self._value_history) >= 2:
            peak: float = self._value_history[0]
            for v in self._value_history:
                peak = max(peak, v)
                if peak > 0:
                    dd: float = (peak - v) / peak
                    max_dd = max(max_dd, dd)

        daily_pnl: float = 0.0
        if len(self._value_history) >= 2:
            daily_pnl = self._value_history[-1] - self._value_history[-2]

        return {
            "total_value": round(self.total_value, 2),
            "cash": round(self.cash, 2),
            "num_positions": len(self.positions),
            "daily_pnl": round(daily_pnl, 2),
            "total_return_pct": round(total_return_pct, 2),
            "sharpe_ratio": round(sharpe, 4),
            "max_drawdown": round(max_dd * 100, 2),
            "total_trades": len(self._trade_history),
        }

    # ═══════════════════════════════════════════════════════════════
    # Persistence (JSON)
    # ═══════════════════════════════════════════════════════════════

    def save_state(self, path: str = "data/portfolio_state.json") -> None:
        """Persist portfolio state to a JSON file.

        Args:
            path: File path for the state JSON.
        """
        file_path: Path = Path(path)
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            state: Dict[str, Any] = {
                "initial_capital": self.initial_capital,
                "cash": self.cash,
                "total_value": self.total_value,
                "positions": self.positions,
                "avg_costs": self.avg_costs,
                "last_prices": self._last_prices,
                "value_history": self._value_history[-100:],  # Keep last 100 entries.
                "daily_returns": self._daily_returns[-252:],  # ~1 year.
                "tiger_synced": self._tiger_initial_capital_synced,
                "saved_at": datetime.now().isoformat(),
            }
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
            logger.debug(
                f"Portfolio state saved: {len(self.positions)} positions, "
                f"cash ${self.cash:.2f}"
            )
        except Exception as exc:
            logger.error(f"Failed to save portfolio state to {path}: {exc}")

    def load_state(self, path: str = "data/portfolio_state.json") -> Optional[Dict[str, Any]]:
        """Load portfolio state from a JSON file.

        Args:
            path: File path for the state JSON.

        Returns:
            Dict with loaded state summary, or None if the file was not found
            or could not be parsed.
        """
        file_path: Path = Path(path)
        if not file_path.exists():
            logger.info(f"No saved portfolio state at {path}")
            return None

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                state: Dict[str, Any] = json.load(f)

            self.initial_capital = float(state.get("initial_capital", self.initial_capital))
            self.cash = float(state.get("cash", self.cash))
            self.total_value = float(state.get("total_value", self.total_value))
            self._tiger_initial_capital_synced = bool(
                state.get("tiger_synced", False)
            )

            # Restore positions.
            positions_raw: Dict[str, float] = state.get("positions", {})
            avg_costs_raw: Dict[str, float] = state.get("avg_costs", {})
            self.positions = {str(k): float(v) for k, v in positions_raw.items()}
            self.avg_costs = {str(k): float(v) for k, v in avg_costs_raw.items()}

            # Restore last prices.
            prices_raw: Dict[str, float] = state.get("last_prices", {})
            self._last_prices = {str(k): float(v) for k, v in prices_raw.items()}

            # Restore value history.
            vh: List[float] = [float(v) for v in state.get("value_history", [])]
            if vh:
                self._value_history = vh

            dr: List[float] = [float(v) for v in state.get("daily_returns", [])]
            if dr:
                self._daily_returns = dr

            logger.info(
                f"Portfolio state loaded from {path}: "
                f"{len(self.positions)} positions, cash ${self.cash:.2f}"
            )

            return {
                "loaded": True,
                "positions": len(self.positions),
                "cash": self.cash,
                "total_value": self.total_value,
                "initial_capital": self.initial_capital,
            }

        except json.JSONDecodeError as exc:
            logger.warning(f"Portfolio state file {path} is corrupt: {exc}")
            return None
        except Exception as exc:
            logger.error(f"Failed to load portfolio state from {path}: {exc}")
            return None

    # ═══════════════════════════════════════════════════════════════
    # Helpers
    # ═══════════════════════════════════════════════════════════════

    def reset(self) -> None:
        """Reset portfolio to initial state."""
        self.cash = self.initial_capital
        self.positions.clear()
        self.avg_costs.clear()
        self._last_prices.clear()
        self.total_value = self.initial_capital
        self._trade_history.clear()
        self._value_history = [self.initial_capital]
        self._daily_returns.clear()
        self._tiger_initial_capital_synced = False
        logger.info("PortfolioManager reset to initial state")

    def apply_liquidation(
        self,
        liquidation_records: List[Dict[str, Any]],
        prices: Optional[Dict[str, float]] = None,
    ) -> None:
        """Apply circuit-breaker liquidation results to local portfolio state.

        Args:
            liquidation_records: Records from ``RiskManager.liquidate_all``.
            prices: Optional price map for ``update_value``.
        """
        if not liquidation_records:
            return

        for rec in liquidation_records:
            if rec.get("order_failed"):
                continue
            ticker = str(rec.get("ticker", ""))
            shares = float(rec.get("shares", 0) or 0)
            price = float(rec.get("price", 0) or 0)
            if not ticker or shares <= 0:
                continue
            held = float(self.positions.get(ticker, 0.0) or 0.0)
            sell_qty = min(held, shares) if held > 0 else shares
            if sell_qty <= 0:
                continue
            px = price if price > 0 else float((prices or {}).get(ticker, 0.0) or 0.0)
            if px <= 0:
                # Force-clear position book without cash credit if price missing
                self.positions.pop(ticker, None)
                self.avg_costs.pop(ticker, None)
                continue
            self.execute_trade(ticker, "SELL", px, sell_qty, strategy="circuit_breaker")

        # Drop zero/failed leftovers and refresh NAV
        self.positions = {t: s for t, s in self.positions.items() if s != 0}
        if prices:
            self.update_value(prices)
        else:
            self.save_state()
        logger.warning(
            f"PortfolioManager: applied {len(liquidation_records)} liquidation records "
            f"| positions={len(self.positions)} cash=${self.cash:,.2f}"
        )
