"""
Backtesting engine — professional historical simulation.
- Multi-horizon backtests
- Full cost model
- Performance report
- Walk-forward validation
"""
from typing import Dict, List, Callable
import numpy as np
import pandas as pd
from loguru import logger

from configs.settings import settings
from backend.trading_engine.portfolio import PortfolioManager
from backend.trading_engine.risk_manager import RiskManager


class Backtester:
    """
    Backtesting engine.
    Simulates trades on historical data to evaluate strategy performance.
    """

    def __init__(self):
        self.results: Dict[str, Dict] = {}

    def run(
        self,
        data_dict: Dict[str, pd.DataFrame],
        signal_generator: Callable,
        initial_capital: float = None,
        commission: float = None,
        start_date: str = None,
        end_date: str = None,
        name: str = "backtest",
    ) -> Dict:
        """
        Run a backtest.

        Args:
            data_dict: {ticker: DataFrame with OHLCV}
            signal_generator: Signal fn(ticker, data, step, positions, cash) -> {decision, strength}
            initial_capital: Starting capital
            commission: Commission rate
            start_date/end_date: Backtest date range
            name: Backtest name

        Returns:
            Backtest result report
        """
        capital = initial_capital or settings.TRADING_INITIAL_CAPITAL

        portfolio = PortfolioManager(capital)
        risk_mgr = RiskManager()

        # Align data
        aligned = self._align_data(data_dict)
        if aligned.empty:
            return {"error": "No data"}

        # Date filter
        if start_date:
            aligned = aligned[aligned.index >= start_date]
        if end_date:
            aligned = aligned[aligned.index <= end_date]

        total_days = len(aligned)
        logger.info(f"🔄 Starting backtest: {name} | {total_days} trading days")

        # Day-by-day backtest
        for step in range(total_days):
            aligned.index[step]

            # Same-day prices
            prices = {}
            for ticker in data_dict.keys():
                col = f"{ticker}_close"
                if col in aligned.columns:
                    price = float(aligned.iloc[step][col])
                    if not np.isnan(price) and price > 0:
                        prices[ticker] = price

            if not prices:
                continue

            # Generate signals
            signals = signal_generator(
                tickers=list(prices.keys()),
                data=aligned,
                step=step,
                positions=portfolio.positions,
                cash=portfolio.cash,
            )

            # Execute trades
            for ticker, signal in signals.items():
                if ticker not in prices:
                    continue
                self._execute_backtest_trade(
                    portfolio, risk_mgr, ticker, signal, prices[ticker]
                )

            # Update portfolio value
            portfolio.update_value(prices)

            # Update risk state
            risk_mgr.update_portfolio_state(
                portfolio.total_value, portfolio.cash,
                portfolio.positions, prices
            )

        # Performance metrics
        result = self._calculate_metrics(portfolio, name)
        self.results[name] = result
        return result

    def _execute_backtest_trade(
        self,
        portfolio: PortfolioManager,
        risk_mgr: RiskManager,
        ticker: str,
        signal: Dict,
        price: float,
    ):
        """Execute a single backtest trade."""
        decision = signal.get("decision", "hold")
        strength = signal.get("strength", 0.0)

        if decision == "hold":
            return

        side = decision
        if side == "buy":
            # Estimated quantity
            estimated_value = portfolio.cash * min(strength, 0.25)
            quantity = estimated_value / price if price > 0 else 0
        else:
            shares = portfolio.positions.get(ticker, 0.0)
            quantity = shares * strength

        report = risk_mgr.check_order(ticker, side, quantity, price)
        if not report.passed:
            return

        portfolio.execute_trade(ticker, side, price, strength)

    def _align_data(self, data_dict: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """Align multi-ticker data onto a shared timeline."""
        aligned = pd.DataFrame()

        for ticker, df in data_dict.items():
            if df.empty:
                continue
            # Extract close and volume
            close = df["close"].rename(f"{ticker}_close")
            volume = df["volume"].rename(f"{ticker}_volume")

            if aligned.empty:
                aligned = pd.DataFrame({f"{ticker}_close": close, f"{ticker}_volume": volume})
            else:
                aligned = aligned.join(
                    pd.DataFrame({f"{ticker}_close": close, f"{ticker}_volume": volume}),
                    how="outer"
                )

        return aligned.sort_index().ffill().bfill().dropna()

    def _calculate_metrics(self, portfolio: PortfolioManager, name: str) -> Dict:
        """Compute backtest performance metrics."""
        metrics = portfolio.get_metrics()
        history = portfolio.get_value_history()

        returns = np.array(portfolio.daily_returns) if portfolio.daily_returns else np.array([0])

        # Annualized return
        total_return = metrics["total_return_pct"] / 100
        n_years = len(returns) / 252 if len(returns) > 0 else 1
        annualized_return = ((1 + total_return) ** (1 / max(n_years, 0.01)) - 1) * 100

        # Annualized volatility
        annualized_vol = returns.std() * np.sqrt(252) * 100 if len(returns) > 5 else 0

        # Sharpe ratio
        sharpe = metrics["sharpe_ratio"]

        # Max drawdown
        max_dd = metrics["max_drawdown"]

        # Win rate
        trades = portfolio.trade_history
        win_trades = sum(1 for t in trades if t["side"] == "sell" and t.get("value", 0) > 0)
        total_sells = sum(1 for t in trades if t["side"] == "sell")
        win_rate = (win_trades / max(total_sells, 1)) * 100

        # Profit factor (simplified)
        profit_factor = 0
        total_profit = sum(
            t["value"] - t["value"] * settings.TRADING_COMMISSION_RATE
            for t in trades if t["side"] == "sell"
        )
        total_loss = sum(
            t["value"] * (1 + settings.TRADING_COMMISSION_RATE)
            for t in trades if t["side"] == "buy"
        )
        if total_loss > 0:
            profit_factor = total_profit / total_loss

        return {
            "name": name,
            "period": f"{history[0]['timestamp'][:10]} → {history[-1]['timestamp'][:10]}",
            "initial_capital": portfolio.initial_capital,
            "final_value": metrics["total_value"],
            "total_return_pct": metrics["total_return_pct"],
            "annualized_return": round(annualized_return, 2),
            "annualized_volatility": round(annualized_vol, 2),
            "sharpe_ratio": sharpe,
            "max_drawdown_pct": max_dd,
            "win_rate": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "total_trades": len(trades),
            "buy_trades": sum(1 for t in trades if t["side"] == "buy"),
            "sell_trades": sum(1 for t in trades if t["side"] == "sell"),
            "value_history": history,
        }

    def compare(self, names: List[str] = None) -> pd.DataFrame:
        """Compare multiple backtest results."""
        if names:
            results = {n: self.results[n] for n in names if n in self.results}
        else:
            results = self.results

        if not results:
            return pd.DataFrame()

        rows = []
        for name, r in results.items():
            if "error" in r:
                continue
            rows.append({
                "name": name,
                "ann_return_pct": r.get("annualized_return", 0),
                "sharpe": r.get("sharpe_ratio", 0),
                "max_dd_pct": r.get("max_drawdown_pct", 0),
                "win_rate_pct": r.get("win_rate", 0),
                "trades": r.get("total_trades", 0),
                "final_value": r.get("final_value", 0),
            })

        return pd.DataFrame(rows)
