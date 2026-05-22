"""
订单执行器
- 实盘：调用 Tiger Brokers API 下单
- 模拟：本地 Paper Trading 撮合
- 风控前置检查
- 交易记录持久化
"""
from typing import Dict, List, Optional, Callable
from loguru import logger

from backend.config import trading_config
from backend.trading_engine.risk_manager import RiskManager
from backend.trading_engine.portfolio import PortfolioManager
from backend.data_engine.tiger_client import tiger_client


class PaperExecutor:
    """
    订单执行器
    - tiger_client 已连接时，执行实盘下单
    - 否则降级为 Paper Trading 模拟
    """

    def __init__(self, portfolio: PortfolioManager, risk_manager: RiskManager):
        self.portfolio = portfolio
        self.risk_manager = risk_manager
        self._order_callbacks: List[Callable] = []
        self.pending_orders: List[Dict] = []
        self.filled_orders: List[Dict] = []
        # 是否使用老虎实盘下单（动态检查，在 execute_signal 中判断）
        self._tiger_account = trading_config.TIGER_ACCOUNT
        if self._tiger_account:
            logger.info(f"📝 老虎账号已配置: {self._tiger_account}（将在下单时动态检查连接）")
        else:
            logger.info("📝 老虎账号未配置，使用模拟模式")

    # ================================================================
    # 订单执行
    # ================================================================

    def execute_signal(
        self,
        ticker: str,
        decision: str,
        strength: float,
        price: float,
        confidence: float = 0.5,
        strategy: str = "ensemble",
    ) -> Optional[Dict]:
        """
        根据信号执行交易

        Args:
            ticker: 股票代码
            decision: buy / sell / hold
            strength: 信号强度 0~1
            price: 当前价格
            confidence: 置信度 0~1
            strategy: 策略名称

        Returns:
            trade_record or None
        """
        # Hold 信号不执行
        if decision == "hold":
            return None

        # 置信度门槛
        if confidence < trading_config.MIN_CONFIDENCE:
            return None

        side = decision  # buy or sell

        # 1. 风控检查
        if side == "buy":
            buy_strength = min(strength, trading_config.MAX_POSITION_SIZE)
            estimated_value = self.portfolio.cash * buy_strength
            quantity = estimated_value / price if price > 0 else 0
            if quantity < trading_config.MIN_SHARES:
                return None
        else:
            shares = self.portfolio.positions.get(ticker, 0.0)
            if shares < trading_config.MIN_SHARES:
                return None  # 无仓位不卖
            quantity = shares * strength
            if quantity < trading_config.MIN_SHARES:
                quantity = shares  # 少于最小量则全卖

        # 最小交易额检查
        if quantity * price < trading_config.MIN_TRADE_VALUE:
            return None

        report = self.risk_manager.check_order(ticker, side, quantity, price)

        if not report.passed:
            logger.warning(f"🔴 风控拒绝: {ticker} {side} | {report.violations}")
            return None

        # 2. 执行交易
        # 优先：本地模拟撮合（保证交易逻辑正常运行）
        trade = self.portfolio.execute_trade(
            ticker=ticker,
            side=side,
            price=price,
            signal_strength=strength,
            strategy=strategy,
        )
        
        if trade:
            self.filled_orders.append(trade)
            self._emit_order_filled(trade)
            
            # 同时发送到老虎实盘（如果已配置且连接）
            use_tiger_now = bool(self._tiger_account and tiger_client.is_connected())
            if use_tiger_now:
                try:
                    action = "BUY" if side == "buy" else "SELL"
                    order_result = tiger_client.place_order(
                        ticker=ticker,
                        action=action,
                        quantity=int(quantity),
                        order_type="MKT",
                        limit_price=price,  # HK 需 LMT，自动转换
                    )
                    if order_result:
                        logger.info(f"✅ 实盘下单成功: {ticker} {action} | 订单ID: {order_result.get('order_id')}")
                    else:
                        logger.warning(f"⚠️ 实盘下单返回空: {ticker} {action}")
                except Exception as e:
                    logger.error(f"❌ 老虎下单异常: {ticker} {action} | {e}")
            
            return trade
        
        return None

    def execute_signal_batch(
        self,
        signals: Dict[str, Dict],
        prices: Dict[str, float],
    ) -> List[Dict]:
        """
        批量执行多个信号

        Args:
            signals: {ticker: {decision, strength, confidence}}
            prices: {ticker: price}

        Returns:
            成交记录列表
        """
        trades = []

        # 按信号强度排序，优先执行高置信度信号
        sorted_signals = sorted(
            signals.items(),
            key=lambda x: x[1].get("confidence", 0) * abs(x[1].get("strength", 0)),
            reverse=True,
        )

        for ticker, signal in sorted_signals:
            price = prices.get(ticker)
            if price is None or price <= 0:
                continue

            trade = self.execute_signal(
                ticker=ticker,
                decision=signal["decision"],
                strength=signal["strength"],
                price=price,
                confidence=signal.get("confidence", 0.5),
            )

            if trade:
                trades.append(trade)

        return trades

    # ================================================================
    # 回调
    # ================================================================

    def on_order_filled(self, callback: Callable):
        """注册成交回调"""
        self._order_callbacks.append(callback)

    def _emit_order_filled(self, trade: Dict):
        """触发成交回调"""
        for cb in self._order_callbacks:
            try:
                cb(trade)
            except Exception as e:
                logger.error(f"❌ 回调错误: {e}")

    # ================================================================
    # Tiger Brokers 适配（预留）
    # ================================================================

    def _tiger_place_order(self, ticker: str, side: str, quantity: float, price: float):
        """
        老虎证券下单（预留）
        切换到实盘时启用
        """
        # from tiger_open_python_sdk import TigerApiClient
        # client = TigerApiClient(trading_config.TIGER_ID, ...)
        # order = client.place_order(
        #     account=trading_config.TIGER_ACCOUNT,
        #     symbol=ticker,
        #     action="BUY" if side == "buy" else "SELL",
        #     quantity=int(quantity),
        #     order_type="LMT" if price else "MKT",
        #     limit_price=price,
        # )
        raise NotImplementedError("Tiger Brokers 实盘待接入")

    def get_execution_summary(self) -> Dict:
        """获取执行摘要"""
        return {
            "total_filled": len(self.filled_orders),
            "total_pending": len(self.pending_orders),
            "buy_count": len([t for t in self.filled_orders if t["side"] == "buy"]),
            "sell_count": len([t for t in self.filled_orders if t["side"] == "sell"]),
        }
