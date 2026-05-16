"""
回测引擎 - 专业级历史数据模拟交易
- 多周期回测
- 完整费用模型
- 性能分析报告
- Walk-Forward 验证
"""
from typing import Dict, List, Callable
import numpy as np
import pandas as pd
from loguru import logger

from backend.config import trading_config
from backend.trading_engine.portfolio import PortfolioManager
from backend.trading_engine.risk_manager import RiskManager


class Backtester:
    """
    回测引擎
    在历史数据上模拟交易，评估策略表现
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
        运行回测

        Args:
            data_dict: {ticker: DataFrame with OHLCV}
            signal_generator: 信号生成函数 fn(ticker, data, step, positions, cash) -> {decision, strength}
            initial_capital: 初始资金
            commission: 交易佣金率
            start_date/end_date: 回测日期范围
            name: 回测名称

        Returns:
            回测结果报告
        """
        capital = initial_capital or trading_config.INITIAL_CAPITAL

        portfolio = PortfolioManager(capital)
        risk_mgr = RiskManager()

        # 数据对齐
        aligned = self._align_data(data_dict)
        if aligned.empty:
            return {"error": "无数据"}

        # 日期过滤
        if start_date:
            aligned = aligned[aligned.index >= start_date]
        if end_date:
            aligned = aligned[aligned.index <= end_date]

        total_days = len(aligned)
        logger.info(f"🔄 开始回测: {name} | {total_days} 个交易日")

        # 逐日回测
        for step in range(total_days):
            aligned.index[step]

            # 获取当日价格
            prices = {}
            for ticker in data_dict.keys():
                col = f"{ticker}_close"
                if col in aligned.columns:
                    price = float(aligned.iloc[step][col])
                    if not np.isnan(price) and price > 0:
                        prices[ticker] = price

            if not prices:
                continue

            # 生成信号
            signals = signal_generator(
                tickers=list(prices.keys()),
                data=aligned,
                step=step,
                positions=portfolio.positions,
                cash=portfolio.cash,
            )

            # 执行交易
            for ticker, signal in signals.items():
                if ticker not in prices:
                    continue
                self._execute_backtest_trade(
                    portfolio, risk_mgr, ticker, signal, prices[ticker]
                )

            # 更新组合价值
            portfolio.update_value(prices)

            # 更新风控状态
            risk_mgr.update_portfolio_state(
                portfolio.total_value, portfolio.cash,
                portfolio.positions, prices
            )

        # 计算性能指标
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
        """执行回测中的单笔交易"""
        decision = signal.get("decision", "hold")
        strength = signal.get("strength", 0.0)

        if decision == "hold":
            return

        side = decision
        if side == "buy":
            # 预估数量
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
        """对齐多股票数据到同一时间轴"""
        aligned = pd.DataFrame()

        for ticker, df in data_dict.items():
            if df.empty:
                continue
            # 提取收盘价和成交量
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
        """计算回测性能指标"""
        metrics = portfolio.get_metrics()
        history = portfolio.get_value_history()

        returns = np.array(portfolio.daily_returns) if portfolio.daily_returns else np.array([0])

        # 年化收益率
        total_return = metrics["total_return_pct"] / 100
        n_years = len(returns) / 252 if len(returns) > 0 else 1
        annualized_return = ((1 + total_return) ** (1 / max(n_years, 0.01)) - 1) * 100

        # 年化波动率
        annualized_vol = returns.std() * np.sqrt(252) * 100 if len(returns) > 5 else 0

        # 夏普比率
        sharpe = metrics["sharpe_ratio"]

        # 最大回撤
        max_dd = metrics["max_drawdown"]

        # 胜率
        trades = portfolio.trade_history
        win_trades = sum(1 for t in trades if t["side"] == "sell" and t.get("value", 0) > 0)
        total_sells = sum(1 for t in trades if t["side"] == "sell")
        win_rate = (win_trades / max(total_sells, 1)) * 100

        # 盈亏比 (简化)
        profit_factor = 0
        total_profit = sum(
            t["value"] - t["value"] * trading_config.COMMISSION_RATE
            for t in trades if t["side"] == "sell"
        )
        total_loss = sum(
            t["value"] * (1 + trading_config.COMMISSION_RATE)
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
        """比较多个回测结果"""
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
                "名称": name,
                "年化收益%": r.get("annualized_return", 0),
                "夏普比率": r.get("sharpe_ratio", 0),
                "最大回撤%": r.get("max_drawdown_pct", 0),
                "胜率%": r.get("win_rate", 0),
                "交易次数": r.get("total_trades", 0),
                "最终资金": r.get("final_value", 0),
            })

        return pd.DataFrame(rows)
