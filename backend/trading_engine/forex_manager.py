"""
Forex Manager — 多币种自动换汇管理器

跨 USD/HKD/SGD 自动换汇，确保各市场有足够资金执行交易。
使用 Tiger API 的 currency_exchange (若可用) 或记录日志供手动操作。

P2: 全品种扫描 + 自动换汇 + 整手预测 + 资金过滤
"""
from __future__ import annotations

from typing import Dict, Optional, List
from dataclasses import dataclass, field

from loguru import logger
from configs.settings import settings


# 币种列表
SUPPORTED_CURRENCIES = ["USD", "HKD", "SGD"]

# 最低换汇金额阈值 (USD 等价)
MIN_FOREX_AMOUNT_USD = 10.0

# 各市场预留缓冲金 (本地货币)
MARKET_BUFFER = {
    "USD": 50.0,
    "HKD": 500.0,   # ~$64 USD
    "SGD": 100.0,   # ~$75 USD
}


@dataclass
class ForexOrder:
    """换汇订单"""
    from_currency: str
    to_currency: str
    amount: float  # from_currency 的数量
    amount_usd: float  # USD 等价
    rate: float  # from→to 汇率
    reason: str

    def __repr__(self):
        return (f"Forex: {self.from_currency} {self.amount:.2f} → "
                f"{self.to_currency} ({self.amount_usd:.2f} USD) [{self.reason}]")


class ForexManager:
    """
    自动换汇管理器。

    逻辑:
    1. 每轮交易前，评估各市场资金需求
    2. 若某市场现金不足，从多余市场换汇
    3. 通过 Tiger API 执行换汇 (若支持) 或生成警报
    """

    def __init__(self, tiger_client=None):
        self._tiger = tiger_client
        self._pending_orders: List[ForexOrder] = []
        self._executed_orders: List[ForexOrder] = []
        self._last_forex_time: float = 0
        self._min_interval = 300  # 最小换汇间隔 5 分钟

    # ── 核心: 评估换汇需求 ──
    def evaluate(
        self,
        account_segments: Dict[str, Dict],
        target_trades: List[Dict],
    ) -> List[ForexOrder]:
        """
        基于账户细分和待执行交易，评估换汇需求。

        Args:
            account_segments: Tiger get_account_segments() 返回值
                {"US": {"cash": ..., "market_value": ...}, "HK": {...}, ...}
            target_trades: 待执行交易列表
                [{"ticker": "AAPL", "side": "buy", "value": 500, "currency": "USD"}, ...]

        Returns:
            换汇订单列表 (按优先级排序)
        """
        import time
        now = time.time()
        if now - self._last_forex_time < self._min_interval:
            return []  # 冷却中

        # 1. 计算各市场当前可用现金 (USD 等价)
        cash_usd = {}
        for ccy in SUPPORTED_CURRENCIES:
            rate = settings.trading_currency_rates_dict.get(ccy, 1.0)
            seg = account_segments.get(ccy, {})
            local_cash = seg.get("cash", 0)
            cash_usd[ccy] = local_cash * rate

        total_usd = sum(cash_usd.values())
        if total_usd < 100:
            return []  # 资金太少不换汇

        # 2. 计算各市场交易需求 (USD 等价)
        demand_usd = {"USD": 0.0, "HKD": 0.0, "SGD": 0.0}
        for trade in target_trades:
            if trade.get("side") != "buy":
                continue
            ccy = trade.get("currency", "USD")
            value_usd = trade.get("value", 0) * settings.trading_currency_rates_dict.get(ccy, 1.0)
            demand_usd[ccy] += value_usd

        # 3. 检测缺口 — 哪些市场现金不足
        orders = []
        for ccy in ["HKD", "SGD", "USD"]:
            available = cash_usd.get(ccy, 0)
            buffer = MARKET_BUFFER.get(ccy, 50) * settings.trading_currency_rates_dict.get(ccy, 1.0)
            needed = demand_usd.get(ccy, 0) + buffer

            if needed > available:
                deficit = needed - available
                # 找有多余现金的市场
                for src_ccy in ["USD", "HKD", "SGD"]:
                    if src_ccy == ccy:
                        continue
                    src_available = cash_usd.get(src_ccy, 0)
                    src_demand = demand_usd.get(src_ccy, 0)
                    src_buffer = MARKET_BUFFER.get(src_ccy, 50) * settings.trading_currency_rates_dict.get(src_ccy, 1.0)
                    src_surplus = src_available - src_demand - src_buffer

                    if src_surplus > MIN_FOREX_AMOUNT_USD and deficit > MIN_FOREX_AMOUNT_USD:
                        amount_usd = min(deficit, src_surplus)
                        # 转回源币种数量
                        src_rate = settings.trading_currency_rates_dict.get(src_ccy, 1.0)
                        amount_from = amount_usd / src_rate
                        # 汇率: from→to
                        to_rate = settings.trading_currency_rates_dict.get(ccy, 1.0)
                        exchange_rate = src_rate / to_rate

                        order = ForexOrder(
                            from_currency=src_ccy,
                            to_currency=ccy,
                            amount=round(amount_from, 2),
                            amount_usd=round(amount_usd, 2),
                            rate=round(exchange_rate, 4),
                            reason=f"资金缺口: {ccy} 需 {needed:.0f}, 缺 {deficit:.0f} USD",
                        )
                        orders.append(order)
                        cash_usd[src_ccy] -= amount_usd
                        cash_usd[ccy] += amount_usd
                        break

        return orders

    # ── 执行换汇 ──
    def execute(self, orders: List[ForexOrder]) -> List[Dict]:
        """
        执行换汇订单。

        Tiger API 可能不支持直接换汇 — 若无法执行则记录日志并返回状态。
        """
        results = []
        import time

        for order in orders:
            logger.info(f"💱 {order}")
            result = {
                "from": order.from_currency,
                "to": order.to_currency,
                "amount": order.amount,
                "amount_usd": order.amount_usd,
                "rate": order.rate,
                "status": "pending",
                "message": "",
            }

            # 尝试通过 Tiger API 执行换汇
            if self._tiger and self._tiger.is_connected():
                try:
                    # Tiger SDK: 尝试 currency_exchange
                    trade_client = self._tiger._trade_client
                    if hasattr(trade_client, 'forex_exchange'):
                        fx_result = trade_client.forex_exchange(
                            from_currency=order.from_currency,
                            to_currency=order.to_currency,
                            amount=order.amount,
                        )
                        result["status"] = "executed"
                        result["order_id"] = getattr(fx_result, 'id', '')
                        result["message"] = f"Tiger 换汇成功"
                        logger.info(f"  ✅ 换汇已执行: {result['message']}")
                    else:
                        result["status"] = "alert"
                        result["message"] = "Tiger API 不支持自动换汇 — 已记录待手动操作"
                        logger.warning(f"  ⚠️ {result['message']}")
                except Exception as e:
                    result["status"] = "failed"
                    result["message"] = f"换汇失败: {e}"
                    logger.error(f"  ❌ {result['message']}")
            else:
                result["status"] = "offline"
                result["message"] = "Tiger 未连接 — 仅记录日志"
                logger.info(f"  📝 {result['message']}")

            results.append(result)
            self._pending_orders.append(order)

        self._last_forex_time = time.time()
        return results

    # ── 自动换汇 (一键方法) ──
    def auto_forex(
        self,
        account_segments: Dict[str, Dict],
        target_trades: List[Dict],
    ) -> Dict:
        """
        自动化换汇入口: 评估 → 执行 → 返回结果。

        Returns:
            {
                "orders": [...],        # 换汇订单
                "results": [...],       # 执行结果
                "total_converted_usd": 0,  # 总换汇金额 USD
            }
        """
        orders = self.evaluate(account_segments, target_trades)

        if not orders:
            return {"orders": [], "results": [], "total_converted_usd": 0}

        total_usd = sum(o.amount_usd for o in orders)
        logger.info(f"💱 自动换汇: {len(orders)} 笔, 总计 ${total_usd:,.2f} USD")

        results = self.execute(orders)
        return {
            "orders": [{
                "from": o.from_currency,
                "to": o.to_currency,
                "amount": o.amount,
                "amount_usd": o.amount_usd,
                "reason": o.reason,
            } for o in orders],
            "results": results,
            "total_converted_usd": total_usd,
        }

    # ── 汇率查询 ──
    @staticmethod
    def get_fx_rate(from_ccy: str, to_ccy: str) -> float:
        """获取两种币种间汇率"""
        from_rate = settings.trading_currency_rates_dict.get(from_ccy, 1.0)
        to_rate = settings.trading_currency_rates_dict.get(to_ccy, 1.0)
        return from_rate / to_rate

    # ── 工具: 计算交易本地货币价值 ──
    @staticmethod
    def calc_trade_local_value(
        ticker: str,
        quantity: float,
        price: float,
    ) -> dict:
        """计算交易的本地货币价值和 USD 等值"""
        from backend.trading_engine.portfolio import PortfolioManager

        pm = PortfolioManager.__new__(PortfolioManager)
        currency = pm._get_currency(ticker) if hasattr(pm, '_get_currency') else "USD"

        local_value = quantity * price
        usd_value = local_value * settings.trading_currency_rates_dict.get(currency, 1.0)

        return {
            "currency": currency,
            "local_value": round(local_value, 2),
            "usd_value": round(usd_value, 2),
        }

    # ── 摘要 ──
    def get_status(self) -> Dict:
        return {
            "pending_orders": len(self._pending_orders),
            "executed_orders": len(self._executed_orders),
            "total_converted": sum(o.amount_usd for o in self._executed_orders),
            "last_forex_time": self._last_forex_time,
        }


# 全局单例
forex_manager = ForexManager()
