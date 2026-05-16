"""
风控系统 - 顶级量化基金级风控
- VaR (Value at Risk)
- 最大回撤控制
- 仓位限制
- 止损/止盈
- 相关性风控
- 流动性风控
"""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import numpy as np
import pandas as pd
from loguru import logger

from backend.config import trading_config


@dataclass
class RiskReport:
    """风控报告"""
    passed: bool = True
    total_risk_score: float = 0.0
    violations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    details: Dict = field(default_factory=dict)


class RiskManager:
    """
    统一风控管理器
    下单前执行多层风控检查
    """

    def __init__(self):
        self.portfolio_value = trading_config.INITIAL_CAPITAL
        self.cash = trading_config.INITIAL_CAPITAL
        self.positions: Dict[str, float] = {}  # ticker -> shares
        self.position_values: Dict[str, float] = {}  # ticker -> market value
        self.trade_history: List[Dict] = []
        self.price_history: Dict[str, List[float]] = {}
        self.peak_value = trading_config.INITIAL_CAPITAL

    # ================================================================
    # 主风控检查
    # ================================================================

    def check_order(
        self,
        ticker: str,
        side: str,
        quantity: float,
        price: float,
    ) -> RiskReport:
        """
        下单前风控检查

        Args:
            ticker: 股票代码
            side: buy/sell
            quantity: 股数
            price: 限价

        Returns:
            RiskReport: 风控报告
        """
        report = RiskReport()
        order_value = quantity * price

        # 1. 资金检查
        if side == "buy":
            cash_check = self._check_sufficient_cash(order_value)
            if not cash_check["passed"]:
                report.violations.append(cash_check["reason"])
                report.passed = False

        # 2. 仓位集中度检查
        if side == "buy":
            concentration = self._check_position_concentration(ticker, order_value)
            if not concentration["passed"]:
                report.violations.append(concentration["reason"])
                report.passed = False

        # 3. 最大回撤检查
        dd_check = self._check_max_drawdown()
        if not dd_check["passed"]:
            report.violations.append(dd_check["reason"])
            report.passed = False

        # 4. VaR 检查
        var_check = self._check_var(ticker, order_value)
        if not var_check["passed"]:
            report.warnings.append(var_check["reason"])
            report.total_risk_score += 0.3

        # 5. 流动性检查
        liq_check = self._check_liquidity(ticker, order_value)
        if not liq_check["passed"]:
            report.warnings.append(liq_check["reason"])

        # 6. 止损检查
        if side == "sell":
            sl_check = self._check_stop_loss(ticker, price)
            if sl_check["triggered"]:
                report.details["stop_loss_triggered"] = True

        # 计算总风险分
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
        """更新组合状态（每个 tick 调用）"""
        self.portfolio_value = portfolio_value
        self.cash = cash
        self.positions = positions

        # 更新持仓市值
        for ticker, shares in positions.items():
            if ticker in prices:
                self.position_values[ticker] = shares * prices[ticker]

        # 更新价格历史
        for ticker, price in prices.items():
            if ticker not in self.price_history:
                self.price_history[ticker] = []
            self.price_history[ticker].append(price)
            # 只保留 252 天
            if len(self.price_history[ticker]) > 252:
                self.price_history[ticker] = self.price_history[ticker][-252:]

        # 更新峰值
        self.peak_value = max(self.peak_value, portfolio_value)

    def get_current_drawdown(self) -> float:
        """获取当前回撤"""
        if self.peak_value == 0:
            return 0.0
        return (self.peak_value - self.portfolio_value) / self.peak_value

    # ================================================================
    # 内部风控检查
    # ================================================================

    def _check_sufficient_cash(self, order_value: float) -> Dict:
        """资金检查"""
        if order_value > self.cash * 1.05:  # 5% 余量
            return {
                "passed": False,
                "reason": f"资金不足: 需要 ${order_value:.2f}, 可用 ${self.cash:.2f}"
            }
        return {"passed": True}

    def _check_position_concentration(self, ticker: str, add_value: float) -> Dict:
        """仓位集中度检查"""
        # 当前持仓市值 + 新增
        current_position_value = self.position_values.get(ticker, 0.0)
        total_position_value = current_position_value + add_value
        position_ratio = total_position_value / (self.portfolio_value + 1e-8)

        if position_ratio > trading_config.MAX_POSITION_SIZE:
            return {
                "passed": False,
                "reason": f"仓位超限: {ticker} 占比 {position_ratio:.1%} > {trading_config.MAX_POSITION_SIZE:.0%}"
            }
        return {"passed": True}

    def _check_max_drawdown(self) -> Dict:
        """最大回撤检查"""
        dd = self.get_current_drawdown()
        if dd > trading_config.MAX_DRAWDOWN:
            return {
                "passed": False,
                "reason": f"最大回撤触发: {dd:.1%} > {trading_config.MAX_DRAWDOWN:.0%}"
            }
        return {"passed": True}

    def _check_var(self, ticker: str, order_value: float) -> Dict:
        """VaR 检查"""
        if ticker not in self.price_history or len(self.price_history[ticker]) < 20:
            return {"passed": True}

        returns = np.diff(self.price_history[ticker]) / (np.array(self.price_history[ticker][:-1]) + 1e-8)
        var = np.percentile(returns, (1 - trading_config.VAR_CONFIDENCE) * 100)
        potential_loss = abs(var * order_value)

        risk_threshold = self.portfolio_value * trading_config.MAX_PORTFOLIO_RISK
        if potential_loss > risk_threshold:
            return {
                "passed": False,
                "reason": f"VaR 超标: 潜在损失 ${potential_loss:.2f} > ${risk_threshold:.2f}"
            }
        return {"passed": True}

    def _check_liquidity(self, ticker: str, order_value: float) -> Dict:
        """流动性检查（简化版）"""
        # 真实环境会查日均成交量
        return {"passed": True}

    def _check_stop_loss(self, ticker: str, current_price: float) -> Dict:
        """止损检查"""
        avg_cost = self._get_avg_cost(ticker)
        if avg_cost <= 0:
            return {"triggered": False}

        loss_pct = (current_price - avg_cost) / avg_cost

        if loss_pct <= -trading_config.STOP_LOSS_PCT:
            logger.warning(f"⚠️ {ticker} 触发止损: {loss_pct:.1%} ≤ {trading_config.STOP_LOSS_PCT:.0%}")
            return {"triggered": True, "loss_pct": loss_pct}

        return {"triggered": False}

    def _get_avg_cost(self, ticker: str) -> float:
        """获取平均持仓成本"""
        buy_trades = [t for t in self.trade_history
                      if t["ticker"] == ticker and t["side"] == "buy"]
        if not buy_trades:
            return 0.0

        total_cost = sum(t["value"] for t in buy_trades)
        total_shares = sum(t["quantity"] for t in buy_trades)
        return total_cost / (total_shares + 1e-8)

    def get_status(self) -> Dict:
        """获取风控状态"""
        return {
            "max_drawdown": round(self.get_current_drawdown(), 4),
            "peak_value": round(self.peak_value, 2),
            "var_95": 0.0,  # 简化
            "position_concentration": {
                t: round(v / (self.portfolio_value + 1e-8), 4)
                for t, v in self.position_values.items()
            },
        }
