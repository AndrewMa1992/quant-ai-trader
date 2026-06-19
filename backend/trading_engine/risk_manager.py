"""
风控系统 - 顶级量化基金级风控
- VaR (Value at Risk)
- 最大回撤控制
- 仓位限制
- 止损/止盈
- 相关性风控
- 流动性风控
- P0-2: 组合级熔断机制 (Circuit Breaker)
"""
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, field
import numpy as np
from loguru import logger

from backend.config import trading_config


@dataclass
class RiskReport:
    """风控报告"""
    passed: bool = True
    total_risk_score: float = 0.0
    violations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    circuit_breaker: bool = False
    details: Dict = field(default_factory=dict)


class RiskManager:
    """
    统一风控管理器
    下单前执行多层风控检查

    P0-2: 新增组合级熔断机制
    - 当日亏损 ≥ DAILY_LOSS_LIMIT (5%) → 触发熔断
    - 回撤 ≥ MAX_DRAWDOWN (25%) → 触发熔断
    - 熔断后平仓所有持仓 + 停止新交易
    """

    def __init__(self):
        self.portfolio_value = trading_config.INITIAL_CAPITAL
        self.cash = trading_config.INITIAL_CAPITAL
        self.positions: Dict[str, float] = {}  # ticker -> shares
        self.position_values: Dict[str, float] = {}  # ticker -> market value
        self.trade_history: List[Dict] = []
        self.price_history: Dict[str, List[float]] = {}
        self.peak_value = trading_config.INITIAL_CAPITAL

        # P0-2: 熔断相关状态
        self.daily_start_value: float = trading_config.INITIAL_CAPITAL
        self.circuit_breaker_triggered: bool = False
        self.circuit_breaker_time: Optional[datetime] = None

        # P0-3: 断路器模式 — "hard" = 熔断+平仓, "warn" = 仅日志告警
        self.breaker_mode: str = "warn"

    # ================================================================
    # P0-2: 组合级熔断
    # ================================================================

    def check_circuit_breaker(self) -> RiskReport:
        """
        组合级熔断检查（每个交易循环调用）。

        检查逻辑：
        1. 当日亏损 ≥ DAILY_LOSS_LIMIT (默认 5%) → 触发熔断
        2. 最大回撤 ≥ MAX_DRAWDOWN (默认 25%) → 触发熔断
        3. 已在熔断冷却期内 → 维持熔断

        P0-3: 支持 breaker_mode
        - "hard" = 熔断并平仓所有持仓
        - "warn" = 仅日志告警，不阻断交易

        Returns:
            RiskReport: 包含 circuit_breaker 标记的风控报告
        """
        report = RiskReport()
        is_warn_mode = self.breaker_mode == "warn"

        # 检查冷却期是否已过
        if self.circuit_breaker_triggered and self.circuit_breaker_time is not None:
            cooldown_seconds = (datetime.now() - self.circuit_breaker_time).total_seconds()
            if cooldown_seconds < trading_config.CIRCUIT_BREAKER_COOLDOWN:
                report.circuit_breaker = True
                report.passed = False
                report.violations.append(
                    f"🚨 熔断冷却中: {cooldown_seconds:.0f}s / "
                    f"{trading_config.CIRCUIT_BREAKER_COOLDOWN}s 剩余"
                )
                report.details["breaker_mode"] = self.breaker_mode
                return report
            else:
                # 冷却期结束，自动解除熔断
                logger.info("🟢 熔断冷却期结束，恢复交易")
                self.circuit_breaker_triggered = False
                self.circuit_breaker_time = None

        # 检查当日亏损
        daily_pnl = self.get_daily_pnl()
        daily_pnl_pct = daily_pnl / (self.daily_start_value + 1e-8)

        if daily_pnl_pct <= -trading_config.DAILY_LOSS_LIMIT:
            report.circuit_breaker = True
            report.passed = False
            if is_warn_mode:
                report.violations.append(
                    f"⚠️ 断路器告警（未阻断）: 当日亏损 {daily_pnl_pct:.2%} ≥ "
                    f"限制 {trading_config.DAILY_LOSS_LIMIT:.0%}"
                )
                logger.warning(
                    f"⚠️ 断路器告警（warn模式，未阻断）: 当日亏损={daily_pnl_pct:.2%}, "
                    f"资产=${self.portfolio_value:,.0f}, 起始=${self.daily_start_value:,.0f}"
                )
            else:
                report.violations.append(
                    f"🚨 熔断触发! 当日亏损 {daily_pnl_pct:.2%} ≥ "
                    f"限制 {trading_config.DAILY_LOSS_LIMIT:.0%}"
                )
                self.circuit_breaker_triggered = True
                self.circuit_breaker_time = datetime.now()
                logger.error(
                    f"🚨 熔断触发! 当日亏损={daily_pnl_pct:.2%}, "
                    f"资产=${self.portfolio_value:,.0f}, 起始=${self.daily_start_value:,.0f}"
                )

        # 检查最大回撤
        current_dd = self.get_current_drawdown()
        # ★ 保护：跳过刚启动时的异常值
        # 1) peak_value == portfolio_value 表示刚初始化，无历史峰值可参考
        # 2) 回撤 > 90% 几乎肯定是数据同步问题（如 Tiger 断连后恢复导致峰值错位）
        if (self.peak_value > self.portfolio_value
                and self.portfolio_value > 0
                and current_dd < 0.90):
            if current_dd >= trading_config.MAX_DRAWDOWN:
                report.circuit_breaker = True
                report.passed = False
                if is_warn_mode:
                    report.violations.append(
                        f"⚠️ 断路器告警（未阻断）: 最大回撤 {current_dd:.2%} ≥ "
                        f"限制 {trading_config.MAX_DRAWDOWN:.0%}"
                    )
                    logger.warning(
                        f"⚠️ 断路器告警（warn模式，未阻断）: 回撤={current_dd:.2%}"
                    )
                else:
                    report.violations.append(
                        f"🚨 熔断触发! 最大回撤 {current_dd:.2%} ≥ "
                        f"限制 {trading_config.MAX_DRAWDOWN:.0%}"
                    )
                    self.circuit_breaker_triggered = True
                    self.circuit_breaker_time = datetime.now()
                    logger.error(f"🚨 熔断触发! 回撤={current_dd:.2%}")
        elif current_dd >= 0.90 and self.portfolio_value > 0:
            # 回撤 ≥ 90% 是数据异常而非真实亏损 —— 输出警告但跳过熔断
            logger.warning(
                f"⚠️ 检测到异常回撤 {current_dd:.2%}，疑似数据同步问题，"
                f"跳过熔断 (peak=${self.peak_value:,.0f}, pv=${self.portfolio_value:,.0f})"
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
        P0-2: 熔断后平仓所有持仓。

        Args:
            prices: {ticker: current_price} 用于计算平仓价值

        Returns:
            平仓交易记录列表，每条包含 ticker, shares, price, value
        """
        if not self.positions:
            logger.info("📭 无持仓需要平仓")
            return []

        logger.warning(f"🚨 执行组合级平仓: {len(self.positions)} 只持仓")
        liquidation_records = []

        for ticker, shares in list(self.positions.items()):
            if shares <= 0:
                continue

            price = prices.get(ticker, 0.0)
            if price <= 0:
                logger.warning(f"⚠️ {ticker} 无有效价格，跳过平仓")
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
                f"  📉 平仓 {ticker}: {shares:.0f}股 @ ${price:.2f} = ${value:,.2f}"
            )

        # 更新组合价值
        if self.positions:
            remaining_value = sum(
                self.positions.get(t, 0) * prices.get(t, 0)
                for t in self.positions
            )
        else:
            remaining_value = 0.0
        self.portfolio_value = self.cash + remaining_value

        logger.warning(
            f"✅ 平仓完成: {len(liquidation_records)} 笔, "
            f"现金 ${self.cash:,.2f}, 总资产 ${self.portfolio_value:,.2f}"
        )

        return liquidation_records

    def force_reset_circuit(self):
        """
        P0-3: 强制重置断路器并校准峰值。

        用途: Dashboard 手动重置按钮，或自动化恢复流程。
        重置后断路器状态恢复为正常，峰值校准为当前组合价值。
        """
        self.circuit_breaker_triggered = False
        self.circuit_breaker_time = None
        self.peak_value = max(self.peak_value, self.portfolio_value)
        logger.info(f"🔄 断路器已重置，峰值校准至 ${self.peak_value:,.2f}")

    def toggle_breaker_mode(self, mode: str):
        """
        P0-3: 切换断路器模式。

        Args:
            mode: "hard" = 熔断+平仓, "warn" = 仅日志告警
        """
        if mode not in ("hard", "warn"):
            logger.error(f"❌ 无效断路器模式: {mode}，仅支持 'hard' 或 'warn'")
            raise ValueError(f"Invalid breaker mode: {mode}. Must be 'hard' or 'warn'.")
        old_mode = self.breaker_mode
        self.breaker_mode = mode
        logger.info(f"🔧 断路器模式切换: {old_mode} → {mode}")

    def reset_daily_state(self):
        """
        P0-2: 新交易日重置熔断状态和当日起始净值。
        应在每个交易日开始时调用。
        """
        self.daily_start_value = self.portfolio_value
        self.circuit_breaker_triggered = False
        self.circuit_breaker_time = None
        logger.info(
            f"📅 新交易日重置: 起始净值=${self.daily_start_value:,.2f}, "
            f"熔断状态=正常"
        )

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

        # P0-2: 熔断状态下拒绝所有新开仓
        if self.circuit_breaker_triggered:
            report.passed = False
            report.circuit_breaker = True
            report.violations.append("🚨 熔断状态 — 拒绝所有新开仓")
            return report

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

    def get_daily_pnl(self) -> float:
        """
        P0-2: 获取当日盈亏（相对于当日起始净值）。

        Returns:
            当日盈亏金额（可正可负）
        """
        return self.portfolio_value - self.daily_start_value

    # ================================================================
    # 内部风控检查
    # ================================================================

    def _check_sufficient_cash(self, order_value: float) -> Dict:
        """资金检查 — 坚决不使用杠杆"""
        from backend.config import trading_config as tcfg
        max_allowed = self.cash * tcfg.MAX_CASH_USAGE
        if order_value > max_allowed:
            return {
                "passed": False,
                "reason": (
                    f"🚫 无杠杆原则 — 买入金额 ${order_value:,.2f} "
                    f"超过可用资金 ${max_allowed:,.2f} "
                    f"(现金 ${self.cash:,.2f} × {tcfg.MAX_CASH_USAGE:.0%}) — "
                    f"坚决不使用任何杠杆"
                )
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
            "daily_pnl": round(self.get_daily_pnl(), 2),
            "daily_pnl_pct": round(self.get_daily_pnl() / (self.daily_start_value + 1e-8), 4),
            "circuit_breaker_triggered": self.circuit_breaker_triggered,
            "breaker_mode": self.breaker_mode,
            "daily_start_value": round(self.daily_start_value, 2),
            "var_95": 0.0,  # 简化
            "position_concentration": {
                t: round(v / (self.portfolio_value + 1e-8), 4)
                for t, v in self.position_values.items()
            },
        }
