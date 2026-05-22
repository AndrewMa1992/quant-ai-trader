"""
投资组合管理器
- 多标的持仓管理
- 组合价值追踪
- 收益/风险统计
- 再平衡
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import numpy as np
from loguru import logger

from backend.config import trading_config


class PortfolioManager:
    """
    投资组合管理器
    追踪组合状态、计算各项指标
    支持多币种自动兑换为 USD
    """

    def __init__(self, initial_capital: float = None):
        self.initial_capital = initial_capital or trading_config.INITIAL_CAPITAL
        self.cash = self.initial_capital
        self.positions: Dict[str, float] = {}  # ticker -> shares
        self.avg_costs: Dict[str, float] = {}  # ticker -> avg cost per share (USD)
        self.total_value = self.initial_capital
        self.trade_history: List[Dict] = []

        # 历史记录
        self.value_history: List[Tuple[datetime, float]] = [
            (datetime.now(), self.initial_capital)
        ]
        self.daily_returns: List[float] = []

    # ================================================================
    # 多币种兑换
    # ================================================================

    def _get_currency(self, ticker: str) -> str:
        """根据 ticker 后缀判断币种"""
        ticker_upper = ticker.upper()
        if ".HK" in ticker_upper:
            return "HKD"
        elif ".SI" in ticker_upper:
            return "SGD"
        elif ".AX" in ticker_upper:
            return "AUD"
        elif ".NZ" in ticker_upper:
            return "NZD"
        return "USD"

    def _to_usd(self, amount: float, currency: str) -> float:
        """将任意币种金额转换为 USD"""
        rate = trading_config.CURRENCY_RATES.get(currency, 1.0)
        return amount * rate

    def _from_usd(self, amount_usd: float, currency: str) -> float:
        """将 USD 转换为目标币种"""
        rate = trading_config.CURRENCY_RATES.get(currency, 1.0)
        return amount_usd / rate if rate > 0 else amount_usd

    # ================================================================
    # 持仓操作
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
        执行一次交易

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
        """执行买入（price 为本地币种，内部自动兑换为 USD）"""
        if self.cash <= 0:
            return None

        currency = self._get_currency(ticker)

        # 仓位比例 = 信号强度
        target_ratio = min(signal_strength, trading_config.MAX_POSITION_SIZE)
        order_value_usd = self.cash * target_ratio

        # 最小交易额
        if order_value_usd < trading_config.MIN_TRADE_VALUE:
            return None

        # 本地币种金额
        order_value_local = self._from_usd(order_value_usd, currency)
        quantity = order_value_local / price if price > 0 else 0

        if quantity < trading_config.MIN_SHARES:
            return None

        total_cost_usd = order_value_usd * (1 + trading_config.COMMISSION_RATE)

        if total_cost_usd > self.cash:
            adjusted_usd = self.cash * 0.95
            order_value_local = self._from_usd(adjusted_usd, currency)
            quantity = order_value_local / price
            total_cost_usd = quantity * self._to_usd(price, currency) * (1 + trading_config.COMMISSION_RATE)
            if quantity < trading_config.MIN_SHARES:
                return None

        # 更新持仓（avg_cost 存 USD）
        old_shares = self.positions.get(ticker, 0.0)
        old_cost = self.avg_costs.get(ticker, 0.0)
        price_usd = self._to_usd(price, currency)

        new_shares = old_shares + quantity
        if new_shares > 0:
            self.avg_costs[ticker] = (old_cost * old_shares + price_usd * quantity) / new_shares
        self.positions[ticker] = new_shares
        self.cash -= total_cost_usd

        # 记录
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

        logger.info(f"📈 BUY  {ticker}: {quantity:.2f}股 @ {currency}${price:.2f} = ${quantity*price_usd:.2f} USD")
        return record

    def _execute_sell(
        self, ticker: str, price: float, signal_strength: float, strategy: str
    ) -> Optional[Dict]:
        """执行卖出（price 为本地币种，收入自动兑换为 USD）"""
        shares = self.positions.get(ticker, 0.0)
        if shares < trading_config.MIN_SHARES:
            return None

        currency = self._get_currency(ticker)

        # 卖出比例
        sell_ratio = min(abs(signal_strength), 1.0)
        quantity = shares * sell_ratio

        if quantity < trading_config.MIN_SHARES:
            quantity = shares  # 少于最小量则全卖

        value_local = quantity * price
        value_usd = self._to_usd(value_local, currency)
        commission = value_usd * trading_config.COMMISSION_RATE
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

        logger.info(f"📉 SELL {ticker}: {quantity:.2f}股 @ {currency}${price:.2f} = ${value_usd:.2f} USD")
        return record

    # ================================================================
    # 组合评估
    # ================================================================

    def update_value(self, prices: Dict[str, float]):
        """更新组合总价值（prices 为各币种本地价格，自动兑换 USD）"""
        positions_value = 0.0
        for ticker, shares in self.positions.items():
            if ticker in prices:
                price_local = prices[ticker]
                price_usd = self._to_usd(price_local, self._get_currency(ticker))
                positions_value += shares * price_usd

        self.total_value = self.cash + positions_value
        self.value_history.append((datetime.now(), self.total_value))

        # 计算日收益
        if len(self.value_history) >= 2:
            prev_value = self.value_history[-2][1]
            daily_return = (self.total_value - prev_value) / (prev_value + 1e-8)
            self.daily_returns.append(daily_return)

    def get_positions_summary(self, prices: Dict[str, float]) -> List[Dict]:
        """获取持仓摘要（统一 USD）"""
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
        """获取组合指标"""
        returns = np.array(self.daily_returns) if self.daily_returns else np.array([0.0])

        sharpe = 0.0
        if len(returns) >= 5 and returns.std() > 0:
            sharpe = (returns.mean() / returns.std()) * np.sqrt(252)

        total_pnl = self.total_value - self.initial_capital
        total_return_pct = (self.total_value / self.initial_capital - 1) * 100

        # 最大回撤
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
        """获取价值历史"""
        return [
            {"timestamp": t.isoformat(), "value": v}
            for t, v in self.value_history
        ]

    def reset(self):
        """重置组合"""
        self.cash = self.initial_capital
        self.positions.clear()
        self.avg_costs.clear()
        self.total_value = self.initial_capital
        self.trade_history.clear()
        self.value_history = [(datetime.now(), self.initial_capital)]
        self.daily_returns.clear()

    # ================================================================
    # 持久化
    # ================================================================

    def save_state(self):
        """保存组合状态到数据库"""
        import sqlite3
        from backend.config import DB_PATH

        conn = sqlite3.connect(str(DB_PATH))
        # 创建 positions 表（如果不存在）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS portfolio_positions (
                ticker TEXT PRIMARY KEY,
                shares REAL NOT NULL,
                avg_cost REAL NOT NULL
            )
        """)
        # 清除旧数据
        conn.execute("DELETE FROM portfolio_positions")
        # 写入当前持仓
        for ticker, shares in self.positions.items():
            avg_cost = self.avg_costs.get(ticker, 0.0)
            conn.execute(
                "INSERT INTO portfolio_positions (ticker, shares, avg_cost) VALUES (?, ?, ?)",
                (ticker, shares, avg_cost)
            )

        # 保存交易记录
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
        for trade in self.trade_history[-100:]:  # 只保存最近100笔
            conn.execute(
                """INSERT OR IGNORE INTO trades (ticker, side, quantity, price, value, commission, timestamp, signal_strength, strategy)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (trade['ticker'], trade['side'], trade['quantity'], trade['price'],
                 trade['value'], trade['commission'], trade['timestamp'],
                 trade['signal_strength'], trade['strategy'])
            )
        # 保存账户状态
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
        logger.debug(f"组合状态已保存: {len(self.positions)} 持仓, 现金 ${self.cash:.2f}")

    def load_state(self) -> bool:
        """从数据库加载组合状态"""
        import sqlite3
        from backend.config import DB_PATH

        conn = sqlite3.connect(str(DB_PATH))
        try:
            # 检查是否有保存的账户状态
            account = conn.execute(
                "SELECT cash, initial_capital FROM portfolio_account WHERE id=1"
            ).fetchone()
            if account is None:
                logger.info("无已保存的组合状态，使用默认初始资金")
                return False

            self.cash = account[0]
            self.initial_capital = account[1]

            # 加载持仓
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

            logger.info(f"组合状态已恢复: {len(self.positions)} 持仓, 现金 ${self.cash:.2f}")
            for t, s in self.positions.items():
                logger.info(f"  {t}: {s:.2f} 股, 均价 ${self.avg_costs.get(t, 0):.2f}")
            return True

        except Exception as e:
            logger.warning(f"加载组合状态失败: {e}")
            return False
        finally:
            conn.close()
