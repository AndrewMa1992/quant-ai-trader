"""
Portfolio manager.
- Multi-name position tracking
- NAV tracking
- Return / risk statistics
- Rebalancing
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import numpy as np
from loguru import logger

from configs.settings import settings


class PortfolioManager:
    """
    Portfolio manager.
    Tracks book state and computes metrics.
    Auto-converts multi-currency amounts to USD.
    """

    def __init__(self, initial_capital: float = None):
        self.initial_capital = initial_capital or settings.TRADING_INITIAL_CAPITAL
        self.cash = self.initial_capital
        self.positions: Dict[str, float] = {}  # ticker -> shares
        self.avg_costs: Dict[str, float] = {}  # ticker -> avg cost per share (USD)
        self.total_value = self.initial_capital
        self.trade_history: List[Dict] = []

        # Tiger sync flag: after first sync, initial_capital follows Tiger
        self._tiger_initial_capital_synced = False

        # History
        self.value_history: List[Tuple[datetime, float]] = [
            (datetime.now(), self.initial_capital)
        ]
        self.daily_returns: List[float] = []

    # ================================================================
    # Multi-currency conversion
    # ================================================================

    def _get_currency(self, ticker: str) -> str:
        """Infer currency from ticker."""
        ticker_upper = ticker.upper()
        if ".HK" in ticker_upper:
            return "HKD"
        elif ".SI" in ticker_upper:
            return "SGD"
        elif ".AX" in ticker_upper:
            return "AUD"
        elif ".NZ" in ticker_upper:
            return "NZD"
        # Numeric ticker (1-5 digits) = HK equity
        clean = ticker_upper.replace(".HK", "").replace(".SI", "").strip()
        if clean.isdigit() and len(clean) <= 5:
            return "HKD"
        return "USD"

    def _to_usd(self, amount: float, currency: str) -> float:
        """Convert an amount in any currency to USD."""
        rate = settings.trading_currency_rates_dict.get(currency, 1.0)
        return amount * rate

    def _from_usd(self, amount_usd: float, currency: str) -> float:
        """Convert a USD amount into the target currency."""
        rate = settings.trading_currency_rates_dict.get(currency, 1.0)
        return amount_usd / rate if rate > 0 else amount_usd

    # ================================================================
    # Position operations
    # ================================================================

    def execute_trade(
        self,
        ticker: str,
        side: str,
        price: float,
        signal_strength: float = 0.0,
        strategy: str = "ensemble",
    ) -> Optional[Dict]:
        """
        Execute a single trade.

        Returns:
            trade_record or None if not executed
        """
        if side == "buy":
            return self._execute_buy(ticker, price, signal_strength, strategy)
        elif side == "sell":
            return self._execute_sell(ticker, price, signal_strength, strategy)
        return None

    def _execute_buy(
        self, ticker: str, price: float, signal_strength: float, strategy: str
    ) -> Optional[Dict]:
        """Execute a buy (price is local currency; converted to USD internally)."""
        if self.cash <= 0:
            return None

        currency = self._get_currency(ticker)

        # Position weight = signal strength
        target_ratio = min(signal_strength, settings.TRADING_MAX_POSITION_SIZE)
        order_value_usd = self.cash * target_ratio

        # Minimum notional
        if order_value_usd < settings.TRADING_MIN_TRADE_VALUE:
            return None

        # Local-currency notional
        order_value_local = self._from_usd(order_value_usd, currency)
        quantity = order_value_local / price if price > 0 else 0

        if quantity < settings.TRADING_MIN_SHARES:
            return None

        total_cost_usd = order_value_usd * (1 + settings.TRADING_COMMISSION_RATE)

        if total_cost_usd > self.cash * settings.TRADING_MAX_CASH_USAGE:
            logger.warning(
                f"🚫 No-leverage reject: {ticker} buy | "
                f"cost ${total_cost_usd:,.2f} > available ${self.cash * settings.TRADING_MAX_CASH_USAGE:,.2f} "
                f"(own cash ${self.cash:,.2f} × {settings.TRADING_MAX_CASH_USAGE:.0%}) — leverage is never used"
            )
            return None

        # Update position (avg_cost stored in USD)
        old_shares = self.positions.get(ticker, 0.0)
        old_cost = self.avg_costs.get(ticker, 0.0)
        price_usd = self._to_usd(price, currency)

        new_shares = old_shares + quantity
        if new_shares > 0:
            self.avg_costs[ticker] = (old_cost * old_shares + price_usd * quantity) / new_shares
        self.positions[ticker] = new_shares
        self.cash -= total_cost_usd

        # Record
        record = {
            "ticker": ticker,
            "side": "buy",
            "quantity": round(quantity, 4),
            "price": round(price, 2),
            "price_usd": round(price_usd, 2),
            "currency": currency,
            "value": round(quantity * price, 2),
            "value_usd": round(quantity * price_usd, 2),
            "commission": round(total_cost_usd - order_value_usd, 2),
            "signal_strength": signal_strength,
            "strategy": strategy,
            "timestamp": datetime.now().isoformat(),
        }
        self.trade_history.append(record)

        logger.info(f"📈 BUY  {ticker}: {quantity:.2f} sh @ {currency}${price:.2f} = ${quantity*price_usd:.2f} USD")
        return record

    def _execute_sell(
        self, ticker: str, price: float, signal_strength: float, strategy: str
    ) -> Optional[Dict]:
        """Execute a sell (price is local currency; proceeds converted to USD)."""
        shares = self.positions.get(ticker, 0.0)
        if shares < settings.TRADING_MIN_SHARES:
            return None

        currency = self._get_currency(ticker)

        # Sell ratio
        sell_ratio = min(abs(signal_strength), 1.0)
        quantity = shares * sell_ratio

        if quantity < settings.TRADING_MIN_SHARES:
            quantity = shares  # Sell all if below the minimum size

        value_local = quantity * price
        value_usd = self._to_usd(value_local, currency)
        commission = value_usd * settings.TRADING_COMMISSION_RATE
        net_value = value_usd - commission

        self.cash += net_value
        self.positions[ticker] = shares - quantity

        if self.positions[ticker] < 0.001:
            del self.positions[ticker]
            if ticker in self.avg_costs:
                del self.avg_costs[ticker]

        price_usd = self._to_usd(price, currency)
        record = {
            "ticker": ticker,
            "side": "sell",
            "quantity": round(quantity, 4),
            "price": round(price, 2),
            "price_usd": round(price_usd, 2),
            "currency": currency,
            "value": round(value_local, 2),
            "value_usd": round(value_usd, 2),
            "commission": round(commission, 2),
            "signal_strength": signal_strength,
            "strategy": strategy,
            "timestamp": datetime.now().isoformat(),
        }
        self.trade_history.append(record)

        logger.info(f"📉 SELL {ticker}: {quantity:.2f} sh @ {currency}${price:.2f} = ${value_usd:.2f} USD")
        return record

    # ================================================================
    # Portfolio valuation
    # ================================================================

    def update_value(self, prices: Dict[str, float]):
        """Update NAV (prices are local; auto-converted to USD)."""
        positions_value = 0.0
        for ticker, shares in self.positions.items():
            if ticker in prices:
                price_local = prices[ticker]
                price_usd = self._to_usd(price_local, self._get_currency(ticker))
                positions_value += shares * price_usd

        self.total_value = self.cash + positions_value
        self.value_history.append((datetime.now(), self.total_value))

        # Daily return
        if len(self.value_history) >= 2:
            prev_value = self.value_history[-2][1]
            daily_return = (self.total_value - prev_value) / (prev_value + 1e-8)
            self.daily_returns.append(daily_return)

    def get_positions_summary(self, prices: Dict[str, float]) -> List[Dict]:
        """Return a position summary (unified USD)."""
        summary = []
        for ticker, shares in self.positions.items():
            local_price = prices.get(ticker, 0.0)
            currency = self._get_currency(ticker)
            price_usd = self._to_usd(local_price, currency)
            value_usd = shares * price_usd
            avg_cost = self.avg_costs.get(ticker, 0.0)
            unrealized_pnl = (price_usd - avg_cost) * shares if avg_cost > 0 else 0.0
            unrealized_pnl_pct = (price_usd / avg_cost - 1) * 100 if avg_cost > 0 else 0.0

            summary.append({
                "ticker": ticker,
                "shares": round(shares, 4),
                "avg_cost": round(avg_cost, 2),
                "current_price": round(local_price, 2),
                "current_price_usd": round(price_usd, 2),
                "currency": currency,
                "market_value": round(value_usd, 2),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "unrealized_pnl_pct": round(unrealized_pnl_pct, 2),
                "allocation": round(value_usd / (self.total_value + 1e-8) * 100, 2),
            })

        summary.sort(key=lambda x: x["market_value"], reverse=True)
        return summary

    def get_metrics(self) -> Dict:
        """Return portfolio metrics."""
        returns = np.array(self.daily_returns) if self.daily_returns else np.array([0.0])

        sharpe = 0.0
        if len(returns) >= 5 and returns.std() > 0:
            sharpe = (returns.mean() / returns.std()) * np.sqrt(252)

        total_pnl = self.total_value - self.initial_capital
        total_return_pct = (self.total_value / self.initial_capital - 1) * 100

        # Max drawdown
        max_dd = 0.0
        if len(self.value_history) >= 2:
            values = [v[1] for v in self.value_history]
            peak = values[0]
            for v in values:
                peak = max(peak, v)
                dd = (peak - v) / peak
                max_dd = max(max_dd, dd)

        return {
            "total_value": round(self.total_value, 2),
            "cash": round(self.cash, 2),
            "positions_value": round(self.total_value - self.cash, 2),
            "total_pnl": round(total_pnl, 2),
            "total_return_pct": round(total_return_pct, 2),
            "sharpe_ratio": round(sharpe, 4),
            "max_drawdown": round(max_dd * 100, 2),
            "num_positions": len(self.positions),
            "total_trades": len(self.trade_history),
        }

    def get_value_history(self) -> List[Dict]:
        """Return NAV history."""
        return [
            {"timestamp": t.isoformat(), "value": v}
            for t, v in self.value_history
        ]

    def reset(self):
        """Reset the portfolio."""
        self.cash = self.initial_capital
        self.positions.clear()
        self.avg_costs.clear()
        self.total_value = self.initial_capital
        self.trade_history.clear()
        self.value_history = [(datetime.now(), self.initial_capital)]
        self.daily_returns.clear()

    # ================================================================
    # Persistence
    # ================================================================

    def save_state(self):
        """Persist portfolio state to the database."""
        import sqlite3
        from configs.settings import settings

        conn = sqlite3.connect(str(DB_PATH))
        # Create the positions table if missing
        conn.execute("""
            CREATE TABLE IF NOT EXISTS portfolio_positions (
                ticker TEXT PRIMARY KEY,
                shares REAL NOT NULL,
                avg_cost REAL NOT NULL
            )
        """)
        # Clear previous rows
        conn.execute("DELETE FROM portfolio_positions")
        # Write current positions
        for ticker, shares in self.positions.items():
            avg_cost = self.avg_costs.get(ticker, 0.0)
            conn.execute(
                "INSERT INTO portfolio_positions (ticker, shares, avg_cost) VALUES (?, ?, ?)",
                (ticker, shares, avg_cost)
            )

        # Persist trades
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                value REAL NOT NULL,
                commission REAL DEFAULT 0,
                timestamp TEXT,
                signal_strength REAL DEFAULT 0,
                strategy TEXT DEFAULT 'ensemble',
                status TEXT DEFAULT 'FILLED',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        for trade in self.trade_history[-100:]:  # Keep the latest 100 fills
            conn.execute(
                """INSERT OR IGNORE INTO trades (ticker, side, quantity, price, value, commission, timestamp, signal_strength, strategy)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (trade['ticker'], trade['side'], trade['quantity'], trade['price'],
                 trade['value'], trade['commission'], trade['timestamp'],
                 trade['signal_strength'], trade['strategy'])
            )
        # Persist account state
        conn.execute("""
            CREATE TABLE IF NOT EXISTS portfolio_account (
                id INTEGER PRIMARY KEY,
                cash REAL NOT NULL,
                initial_capital REAL NOT NULL
            )
        """)
        conn.execute("DELETE FROM portfolio_account")
        conn.execute(
            "INSERT INTO portfolio_account (id, cash, initial_capital) VALUES (1, ?, ?)",
            (self.cash, self.initial_capital)
        )
        conn.commit()
        conn.close()
        logger.debug(f"Portfolio saved: {len(self.positions)} positions, cash ${self.cash:.2f}")

    def load_state(self) -> bool:
        """Load portfolio state from the database."""
        import sqlite3
        from configs.settings import settings

        conn = sqlite3.connect(str(DB_PATH))
        try:
            # Check for a saved account snapshot
            account = conn.execute(
                "SELECT cash, initial_capital FROM portfolio_account WHERE id=1"
            ).fetchone()
            if account is None:
                logger.info("No saved portfolio; using default initial capital")
                return False

            self.cash = account[0]
            self.initial_capital = account[1]

            # Load positions
            rows = conn.execute("SELECT ticker, shares, avg_cost FROM portfolio_positions").fetchall()
            self.positions.clear()
            self.avg_costs.clear()
            for ticker, shares, avg_cost in rows:
                self.positions[ticker] = shares
                self.avg_costs[ticker] = avg_cost

            self.total_value = self.cash + sum(
                shares * self.avg_costs.get(ticker, 0)
                for ticker, shares in self.positions.items()
            )

            logger.info(f"Portfolio restored: {len(self.positions)} positions, cash ${self.cash:.2f}")
            for t, s in self.positions.items():
                logger.info(f"  {t}: {s:.2f} sh, avg cost ${self.avg_costs.get(t, 0):.2f}")
            return True

        except Exception as e:
            logger.warning(f"Failed to load portfolio state: {e}")
            return False
        finally:
            conn.close()

    # ================================================================
    # Tiger Brokers live sync
    # ================================================================

    def sync_from_tiger(self, force: bool = False) -> Dict:
        """
        Pull live positions and account info from the Tiger API and overwrite local state.
        This is the sole source of truth.

        Args:
            force: Force a sync even if local data already exists

        Returns:
            {"synced": bool, "positions": int, "cash": float, "total_value": float, "source": str}
        """
        from backend.data_engine.tiger_client import tiger_client

        result = {
            "synced": False,
            "positions": 0,
            "cash": 0.0,
            "total_value": 0.0,
            "source": "none",
        }

        if not tiger_client.is_connected():
            # Try reconnect
            logger.info("🔄 Tiger not connected; retrying...")
            tiger_client.connect()
        
        if not tiger_client.is_connected():
            logger.warning("⚠️ Tiger not connected; cannot sync positions")
            result["source"] = "tiger_offline"
            return result

        try:
            # Ensure the session is valid: reconnect then query
            tiger_client.connect()
            
            # 1. Pull live Tiger positions
            tiger_positions = tiger_client.get_positions()
            tiger_account = tiger_client.get_account_info()

            if not tiger_account:
                logger.warning("⚠️ Unable to fetch Tiger account info")
                result["source"] = "tiger_account_error"
                return result

            # 2. Snapshot local state before overwrite
            old_pos_count = len(self.positions)
            old_cash = self.cash

            # Safety net: Tiger returned 0 positions while local has many — likely API fault; keep local
            if len(tiger_positions) == 0 and old_pos_count > 5:
                logger.error(
                    f"🚨 Tiger returned 0 positions but local has {old_pos_count}!"
                    f"Tiger API may be faulty; keeping local data"
                )
                result["synced"] = False
                result["source"] = "tiger_empty_abnormal"
                result["positions"] = old_pos_count
                result["cash"] = old_cash
                result["total_value"] = self.total_value
                return result

            # 3. Overwrite local state with Tiger data
            self.positions.clear()
            self.avg_costs.clear()
            self.cash = tiger_account.get("cash", 0.0)

            # First Tiger sync: use Tiger NAV as initial_capital
            tiger_total = tiger_account.get("total_value", 0.0)
            if tiger_total > 0:
                # Reset if never synced, gap > 5%, or force=True
                need_reset = (
                    force or
                    not self._tiger_initial_capital_synced or
                    abs(tiger_total - self.initial_capital) / max(self.initial_capital, 1) > 0.05
                )
                if need_reset:
                    reset_reason = "forced reset" if force else (
                        "first sync" if not self._tiger_initial_capital_synced else
                        f"gap {abs(tiger_total-self.initial_capital)/max(self.initial_capital,1)*100:.1f}%"
                    )
                    logger.info(
                        f"🔑 Tiger synced initial_capital ({reset_reason}): "
                        f"${self.initial_capital:,.2f} → ${tiger_total:,.2f}"
                    )
                    self.initial_capital = tiger_total
                    self._tiger_initial_capital_synced = True
                    # Reset value_history origin
                    self.value_history = [(datetime.now(), tiger_total)]

            for pos in tiger_positions:
                ticker = pos.get("ticker", "")
                shares = pos.get("shares", 0.0)
                avg_cost = pos.get("avg_cost", 0.0)
                if ticker:
                    if shares > 0:
                        self.positions[ticker] = shares
                        self.avg_costs[ticker] = avg_cost
                    elif shares < 0:
                        # Negative position = short; needs to be covered
                        self.positions[ticker] = shares  # Keep the negative for repair
                        self.avg_costs[ticker] = avg_cost

            # 4. NAV — Tiger account.total_value is authoritative
            tiger_total = tiger_account.get("total_value", 0.0)
            if tiger_total > 0:
                self.total_value = tiger_total  # Tiger already handles multi-currency
            else:
                positions_value = sum(
                    pos.get("market_value", 0.0) for pos in tiger_positions
                )
                self.total_value = self.cash + positions_value

            # 5. Record sync result
            result["synced"] = True
            pos_count = sum(1 for s in self.positions.values() if s > 0)
            neg_count = sum(1 for s in self.positions.values() if s < 0)
            result["positions"] = pos_count
            result["negative_positions"] = neg_count
            result["cash"] = self.cash
            result["total_value"] = self.total_value
            result["source"] = "tiger_api"

            logger.info(
                f"🔄 Tiger sync complete: "
                f"{pos_count} positions, "
                f"cash ${old_cash:,.2f}→${self.cash:,.2f}, "
                f"NAV ${self.total_value:,.2f}"
            )
            
            if neg_count > 0:
                neg_list = [(t, s) for t, s in self.positions.items() if s < 0]
                neg_tickers = [t for t, _ in neg_list[:10]]
                logger.warning(f"⚠️ Found {neg_count} short position(s): {neg_tickers}")
                result["negative_tickers"] = neg_tickers

            if len(self.positions) > 0:
                logger.info(f"  Tiger position details:")
                for pos in tiger_positions[:40]:  # Cap at 40 names
                    logger.info(
                        f"    {pos['ticker']:10s}: {pos['shares']:>10.2f} sh, "
                        f"MV ${pos.get('market_value', 0):>12,.2f}, "
                        f"avg ${pos.get('avg_cost', 0):>8.2f}"
                    )

            # 6. Persist synced state to the local database immediately
            self.save_state()
            logger.info("  📝 Tiger sync state saved to the local database")

            # Leverage probe
            tiger_leverage = tiger_account.get("leverage", 1.0)
            if tiger_leverage > 1.001:
                tiger_mkt = tiger_account.get("market_value", 0)
                tiger_total = tiger_account.get("total_value", 0)
                margin_amt = tiger_mkt - tiger_total if tiger_mkt > tiger_total else (tiger_leverage - 1.0) * tiger_total
                result["margin_detected"] = True
                result["margin_amount"] = round(margin_amt, 2)
                result["leverage"] = round(tiger_leverage, 4)
                logger.warning(
                    f"⚠️ Tiger leverage detected! Leverage {tiger_leverage:.4f} | "
                    f"MV ${tiger_mkt:,.0f} | net assets ${tiger_total:,.0f}"
                )
            else:
                result["margin_detected"] = False

            return result

        except Exception as e:
            logger.error(f"❌ Tiger sync failed: {e}", exc_info=True)
            result["source"] = "sync_error"
            return result

    def reconcile_with_tiger(self) -> Dict:
        """
        Reconcile with Tiger Brokers: compare local vs live positions.
        Emits a diff report but does not auto-fix (manual confirmation required).

        Returns:
            {"matched": bool, "differences": [...], "local_count": int, "tiger_count": int}
        """
        from backend.data_engine.tiger_client import tiger_client

        result = {
            "matched": True,
            "differences": [],
            "local_count": len(self.positions),
            "tiger_count": 0,
            "local_cash": self.cash,
            "tiger_cash": 0.0,
        }

        if not tiger_client.is_connected():
            # Try reconnect
            tiger_client.connect()
        
        if not tiger_client.is_connected():
            result["matched"] = False
            result["differences"].append({"type": "connection", "msg": "Tiger not connected"})
            return result

        try:
            # Ensure the session is valid
            tiger_client.connect()
            
            tiger_positions = tiger_client.get_positions()
            tiger_account = tiger_client.get_account_info()

            result["tiger_count"] = len(tiger_positions)
            result["tiger_cash"] = tiger_account.get("cash", 0.0) if tiger_account else 0.0

            # Build Tiger position map (ticker -> shares)
            tiger_dict = {}
            for pos in tiger_positions:
                ticker = pos.get("ticker", "")
                shares = pos.get("shares", 0.0)
                if ticker:
                    tiger_dict[ticker] = {
                        "shares": shares,
                        "avg_cost": pos.get("avg_cost", 0.0),
                        "market_value": pos.get("market_value", 0.0),
                    }

            # Diff: local-only names
            local_tickers = set(self.positions.keys())
            tiger_tickers = set(tiger_dict.keys())

            only_local = local_tickers - tiger_tickers
            only_tiger = tiger_tickers - local_tickers
            both = local_tickers & tiger_tickers

            if only_local:
                result["matched"] = False
                for t in only_local:
                    result["differences"].append({
                        "type": "local_only",
                        "ticker": t,
                        "local_shares": self.positions.get(t, 0),
                        "msg": f"Local has a position but Tiger does not: {t}",
                    })

            if only_tiger:
                result["matched"] = False
                for t in only_tiger:
                    result["differences"].append({
                        "type": "tiger_only",
                        "ticker": t,
                        "tiger_shares": tiger_dict[t]["shares"],
                        "msg": f"Tiger has a position but local does not: {t}",
                    })

            # Diff: both sides hold but quantity differs
            for t in both:
                local_shares = self.positions.get(t, 0)
                tiger_shares = tiger_dict[t]["shares"]
                if abs(local_shares - tiger_shares) > 0.01:  # Allow 0.01-share tolerance
                    result["matched"] = False
                    result["differences"].append({
                        "type": "quantity_mismatch",
                        "ticker": t,
                        "local_shares": local_shares,
                        "tiger_shares": tiger_shares,
                        "diff": local_shares - tiger_shares,
                        "msg": f"Quantity mismatch: {t} local {local_shares:.2f} vs Tiger {tiger_shares:.2f}",
                    })

            # Cash comparison
            if abs(self.cash - result["tiger_cash"]) > 1.0:
                result["matched"] = False
                result["differences"].append({
                    "type": "cash_mismatch",
                    "local_cash": self.cash,
                    "tiger_cash": result["tiger_cash"],
                    "diff": self.cash - result["tiger_cash"],
                    "msg": f"Cash mismatch: local ${self.cash:.2f} vs Tiger ${result['tiger_cash']:.2f}",
                })

            if result["matched"]:
                logger.info(f"✅ Tiger reconcile passed: {len(both)} positions match, cash ${self.cash:.2f}")
            else:
                logger.warning(f"⚠️ Tiger reconcile found {len(result['differences'])} difference(s)")
                for diff in result["differences"][:10]:
                    logger.warning(f"    {diff['msg']}")

            return result

        except Exception as e:
            logger.error(f"❌ Tiger reconcile failed: {e}")
            result["matched"] = False
            result["differences"].append({"type": "error", "msg": str(e)})
            return result
