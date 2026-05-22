"""
老虎证券 OpenAPI 客户端
模拟/实盘双模式集成
"""
from typing import Dict, List, Optional
from datetime import datetime
from pathlib import Path
import pandas as pd
from loguru import logger

from backend.config import trading_config


class TigerClient:
    """
    老虎证券 API 客户端
    - 支持模拟账号（Paper Trading）和实盘账号
    - 行情获取、订单管理
    - 封装 tigeropen SDK

    使用前需要：
    1. 在 https://developer.itigerup.com/profile 注册开发者
    2. 获取 tiger_id、account、private_key
    3. 将凭证填入 config.py 或 tiger_openapi_config.properties
    """

    def __init__(self, config_path: Optional[str] = None):
        self._config = None
        self._quote_client = None
        self._trade_client = None
        self._connected = False
        self._config_path = config_path or str(Path.home() / ".tigeropen")
        self._simulation_account = None
        self._real_account = None

    # ================================================================
    # 连接管理
    # ================================================================

    def connect(self) -> bool:
        """
        连接老虎 API

        自动读取配置，支持：
        - 配置文件方式（tiger_openapi_config.properties）
        - 代码直接配置（用 config.py 中的参数）

        Returns: 是否连接成功
        """
        try:
            from tigeropen.tiger_open_config import TigerOpenClientConfig
            from tigeropen.quote.quote_client import QuoteClient
            from tigeropen.trade.trade_client import TradeClient

            # 方式1：配置文件加载
            if Path(self._config_path).exists():
                self._config = TigerOpenClientConfig(props_path=self._config_path)
                logger.info(f"📄 从配置文件加载: {self._config_path}")

            # 方式2：代码直接配置（当 config.py 中有值时）
            elif trading_config.TIGER_ID and trading_config.TIGER_PRIVATE_KEY:
                from backend.config import trading_config as tc

                self._config = TigerOpenClientConfig()
                self._config.tiger_id = tc.TIGER_ID
                self._config.account = tc.TIGER_ACCOUNT
                self._config.private_key = tc.TIGER_PRIVATE_KEY
                logger.info("📄 从 config.py 加载配置")

            else:
                logger.warning("⚠️ 老虎 API 未配置，请在 config.py 填入凭证或放置配置文件")
                return False

            # 初始化客户端
            self._quote_client = QuoteClient(self._config)
            self._trade_client = TradeClient(self._config)
            self._connected = True

            # 获取账号信息
            self._load_accounts()

            logger.info(f"✅ 老虎 API 连接成功！(tiger_id: {trading_config.TIGER_ID})")
            if self._simulation_account:
                logger.info(f"   📝 模拟账号: {self._simulation_account}")
            return True

        except ImportError:
            logger.warning("⚠️ tigeropen 未安装，执行: pip install tigeropen")
            return False
        except Exception as e:
            logger.error(f"❌ 老虎 API 连接失败: {e}")
            return False

    def _load_accounts(self):
        """加载账号列表（实盘和模拟）"""
        try:
            # 使用正确的API方法
            accounts = self._trade_client.get_managed_accounts() if self._trade_client else []
            for acc in accounts:
                acc_str = str(acc.account)
                if len(acc_str) == 17 and acc_str.isdigit():
                    self._simulation_account = acc_str
                else:
                    self._real_account = acc_str

            # 如果没找到，尝试获取资产信息
            if not self._simulation_account and not self._real_account:
                assets = self._trade_client.get_assets()
                if assets:
                    self._simulation_account = str(assets.account)

            logger.info(f"   📝 实盘账号: {self._real_account}")
            logger.info(f"   📝 模拟账号: {self._simulation_account}")
        except Exception as e:
            logger.warning(f"⚠️ 加载账号信息失败: {e}")

    # ================================================================
    # 行情数据
    # ================================================================

    def get_quote(self, ticker: str) -> Optional[Dict]:
        """
        获取实时报价

        Args:
            ticker: 股票代码（如 'AAPL', '00700'）

        Returns:
            { symbol, latest_price, open, high, low, volume, timestamp, ... }
        """
        if not self._connected:
            return None

        try:
            briefs = self._quote_client.get_stock_briefs([ticker])
            if not briefs:
                return None

            brief = briefs[0]
            return {
                "ticker": ticker,
                "price": brief.latest_price,
                "open": brief.open,
                "high": brief.high,
                "low": brief.low,
                "volume": brief.volume,
                "pre_close": brief.pre_close,
                "change": brief.change,
                "change_pct": brief.change_pct,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"❌ 获取 {ticker} 报价失败: {e}")
            return None

    def get_kline(
        self,
        ticker: str,
        period: str = "day",
        begin_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 500,
    ) -> pd.DataFrame:
        """
        获取 K 线数据

        Args:
            ticker: 股票代码
            period: day / week / month / year
            begin_time: 开始时间 "2024-01-01"
            end_time: 结束时间 "2025-01-01"
            limit: 最大条数

        Returns:
            DataFrame with columns: open, high, low, close, volume, timestamp
        """
        if not self._connected:
            return pd.DataFrame()

        try:
            bars = self._quote_client.get_timeline_bars(
                symbol=ticker,
                period=period,
                begin_time=begin_time,
                end_time=end_time,
                limit=limit,
            )

            if not bars:
                return pd.DataFrame()

            records = []
            for bar in bars:
                records.append({
                    "timestamp": bar.time,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                })

            df = pd.DataFrame(records)
            df.set_index("timestamp", inplace=True)
            return df

        except Exception as e:
            logger.error(f"❌ 获取 {ticker} K线失败: {e}")
            return pd.DataFrame()

    # ================================================================
    # 交易操作
    # ================================================================

    def place_order(
        self,
        ticker: str,
        action: str,
        quantity: int,
        order_type: str = "MKT",
        limit_price: Optional[float] = None,
        account: Optional[str] = None,
    ) -> Optional[Dict]:
        """
        下单

        Args:
            ticker: 股票代码
            action: BUY / SELL
            quantity: 股数
            order_type: MKT(市价) / LMT(限价)
            limit_price: 限价单价格
            account: 指定账号（默认用配置中的账号）

        Returns:
            { order_id, status, ... } or None
        """
        if not self._connected:
            logger.error("❌ API 未连接")
            return None

        try:
            from tigeropen.trade.domain.order import Order
            from tigeropen.trade.domain.contract import Contract
            from tigeropen.common.consts import SecurityType, Currency

            # 确定账号（模拟优先）
            target_account = self._simulation_account or self._real_account or trading_config.TIGER_ACCOUNT

            # 确定市场和币种
            is_hk = ticker.endswith('.HK')
            if is_hk:
                market = 'HK'
                currency = Currency.HKD
                symbol = ticker.replace('.HK', '').zfill(5)
                # HK 不支持 MKT，必须用 LMT
                if order_type == 'MKT':
                    if limit_price:
                        order_type = 'LMT'
                    else:
                        logger.warning(f"⚠️ HK 无价格，跳过: {ticker}")
                        return None
            else:
                market = 'US'
                currency = Currency.USD
                symbol = ticker

            # 确保最小数量为 1 股
            qty = int(quantity)
            if qty < 1:
                qty = 1
                logger.warning(f"⚠️ 数量调整为 1 (原始: {quantity})")

            # 构造 Contract 对象
            contract = Contract(
                symbol=symbol,
                currency=currency,
                sec_type=SecurityType.STK,
                exchange=market,
            )

            # 构造 Order 对象
            order = Order(
                account=target_account,
                contract=contract,
                action=action,
                order_type=order_type,
                quantity=qty,
            )
            if limit_price:
                order.limit_price = limit_price

            logger.info(f"📤 下单: {ticker} {action} {int(quantity)}股 @ {order_type}")
            if trading_config.TIGER_PAPER_TRADING:
                logger.info(f"   📝 Paper Trading 模式 (账号: {target_account})")

            result_id = self._trade_client.place_order(order)
            # place_order 返回 global order id (int)，同时更新 order.id
            logger.info(f"✅ 下单成功: {ticker} 订单ID {result_id}, 状态 {order._status}")
            
            return {
                "order_id": result_id,
                "status": str(order._status) if order._status else 'SUBMITTED',
                "symbol": ticker,
                "action": action,
                "quantity": quantity,
                "price": limit_price,
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            error_msg = str(e)
            if 'cannot be placed at this moment' in error_msg.lower():
                logger.info(f"⏰ 市场休市，跳过实盘下单 ({ticker})")
            elif 'must be greater than 0' in error_msg.lower():
                logger.warning(f"⚠️ 参数错误 ({ticker}): {error_msg[:80]}")
            else:
                logger.error(f"❌ 下单失败 ({ticker} {action}): {error_msg[:100]}")
                import traceback
                logger.error(traceback.format_exc())
            return None

    def cancel_order(self, order_id: str) -> bool:
        """撤单"""
        if not self._connected:
            return False
        try:
            self._trade_client.cancel_order(order_id)
            return True
        except Exception as e:
            logger.error(f"❌ 撤单失败: {e}")
            return False

    def get_positions(self) -> List[Dict]:
        """获取持仓"""
        if not self._connected:
            return []

        try:
            positions = self._trade_client.get_positions()
            return [
                {
                    "ticker": p.symbol,
                    "shares": p.quantity,
                    "avg_cost": p.average_cost,
                    "market_value": p.market_value,
                    "realized_pnl": p.realized_pnl,
                    "unrealized_pnl": p.unrealized_pnl,
                }
                for p in (positions or [])
            ]
        except Exception as e:
            logger.error(f"❌ 获取持仓失败: {e}")
            return []

    def get_account_info(self) -> Optional[Dict]:
        """获取账户信息"""
        if not self._connected:
            return None

        try:
            # 使用正确的API方法
            assets = self._trade_client.get_assets(account=self._simulation_account or self._real_account)
            if assets and isinstance(assets, list) and len(assets) > 0:
                a = assets[0]
                # 安全获取账户属性
                summary = a.summary if hasattr(a, 'summary') and a.summary else None
                return {
                    "account": a.account if hasattr(a, 'account') else "",
                    "cash": summary.cash if summary and hasattr(summary, 'cash') else 0,
                    "market_value": summary.stock_market_value if summary and hasattr(summary, 'stock_market_value') else 0,
                    "total_value": summary.net_liquidation if summary and hasattr(summary, 'net_liquidation') else 0,
                    "buying_power": summary.buying_power if summary and hasattr(summary, 'buying_power') else 0,
                    "realized_pnl": 0,
                    "unrealized_pnl": 0,
                }
        except Exception as e:
            logger.error(f"❌ 获取账户信息失败: {e}")
        return None

    # ================================================================
    # 状态
    # ================================================================

    def is_connected(self) -> bool:
        return self._connected

    def get_status(self) -> Dict:
        """获取客户端状态"""
        return {
            "connected": self._connected,
            "simulation_account": self._simulation_account,
            "real_account": self._real_account,
            "has_quote_client": self._quote_client is not None,
            "has_trade_client": self._trade_client is not None,
        }


# 全局单例
tiger_client = TigerClient()
