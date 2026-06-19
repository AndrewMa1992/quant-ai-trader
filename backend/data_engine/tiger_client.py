"""
老虎证券 OpenAPI 客户端
实盘交易
"""
import time
from typing import Dict, List, Optional
from datetime import datetime
from pathlib import Path
import pandas as pd
from loguru import logger

from backend.config import trading_config


class TigerClient:
    """
    老虎证券 API 客户端
    - 支持实盘交易
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
        
        # ★ API 调用频率控制 (Tiger 限制 10次/分钟)
        self._last_account_call = 0.0
        self._last_positions_call = 0.0
        self._cached_account: Optional[Dict] = None
        self._cached_positions: Optional[List[Dict]] = None
        self._min_call_interval = 15.0  # 最小间隔 15 秒

    @property
    def _active_account(self) -> str:
        """根据 SIMULATION_MODE 返回正确账户"""
        if trading_config.SIMULATION_MODE:
            return self._simulation_account or ""
        return self._real_account or ""

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
                # ★ tigeropen 库要求纯 base64（无 PEM 头尾），否则 b64decode 直接炸
                pk = tc.TIGER_PRIVATE_KEY
                if "-----BEGIN" in pk:
                    pk = "".join(pk.splitlines()[1:-1])
                self._config.private_key = pk
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
            if self._real_account:
                logger.info(f"   📝 实盘账号: {self._real_account}")
            return True

        except ImportError:
            logger.warning("⚠️ tigeropen 未安装，执行: pip install tigeropen")
            return False
        except Exception as e:
            logger.error(f"❌ 老虎 API 连接失败: {e}")
            return False

    def _load_accounts(self):
        """加载账号列表（实盘）"""
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
            bars = self._quote_client.get_bars(
                symbols=[ticker],
                period=period,
                begin_time=begin_time,
                end_time=end_time,
                limit=limit,
            )

            if bars is None or bars.empty:
                return pd.DataFrame()

            # get_bars returns DataFrame, rename columns to match our format
            df = bars.copy()
            col_map = {
                'open': 'open', 'high': 'high', 'low': 'low',
                'close': 'close', 'volume': 'volume'
            }
            if 'time' in df.columns:
                df.set_index('time', inplace=True)
            df = df[[c for c in col_map if c in df.columns]]
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

            # 确定账号（根据 SIMULATION_MODE 选择）
            target_account = self._active_account or trading_config.TIGER_ACCOUNT

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
                # ★ 盘前/盘后不支持市价单，自动转为限价单
                if order_type == 'MKT':
                    if limit_price:
                        order_type = 'LMT'
                    else:
                        logger.debug(f"⏸ {ticker} 盘前/盘后无价格，跳过市价单")
                        # Fallback: 从 Tiger 获取实时价
                        quote = self.get_quote(ticker)
                        if quote and quote.get("price", 0) > 0:
                            limit_price = quote["price"]
                            order_type = 'LMT'
                            logger.info(f"📡 Tiger实时价: {ticker} ${limit_price:.2f} (转为限价单)")
                        else:
                            # 无价格时用 last_price/pre_close 兜底
                            limit_price = self._get_last_price_fallback(ticker)
                            if limit_price and limit_price > 0:
                                order_type = 'LMT'
                                logger.info(f"📡 兜底价: {ticker} ${limit_price:.2f} (转为限价单)")
                            else:
                                logger.warning(f"⚠️ {ticker} 盘前/盘后无报价，跳过下单")
                                return None

            # 港股/新加坡股买入：取整到整手（卖出不限制）
            if action == "BUY":
                qty = self.round_to_lot(ticker, quantity)
                if qty < 1:
                    logger.warning(f"⚠️ {ticker} 不足一手 (lot={self.get_hk_lot_size(ticker)}), 下单跳过")
                    return None
            else:
                qty = int(quantity)

            # 构造 Contract 对象
            contract = Contract(
                symbol=symbol,
                currency=currency,
                sec_type=SecurityType.STK,
                exchange=market,
            )

            # 构造 Order 对象 — ★ 支持盘前/盘后交易
            kwargs = {}
            if market == 'US':
                kwargs['outside_rth'] = True  # 24h: 盘前+盘中+盘后+夜盘 (4:00-次日4:00 ET)
            order = Order(
                account=target_account,
                contract=contract,
                action=action,
                order_type=order_type,
                quantity=qty,
                **kwargs,
            )
            if limit_price:
                # HK 价格 tick size 对齐
                if is_hk:
                    limit_price = self._align_hk_tick(limit_price)
                order.limit_price = limit_price

            extended_label = " [24h扩展]" if kwargs.get('outside_rth') else ""
            logger.info(f"📤 下单: {ticker} {action} {int(quantity)}股 @ {order_type}{extended_label} (账号: {target_account})")

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

    def get_positions(self, force: bool = False) -> List[Dict]:
        """获取持仓 — 带缓存避免 API 限流"""
        now = time.time()
        if not force and self._cached_positions is not None and (now - self._last_positions_call) < self._min_call_interval:
            logger.debug(f"♻️ 使用缓存持仓 ({len(self._cached_positions)} 只, {now - self._last_positions_call:.0f}s 前)")
            return self._cached_positions
        
        if not self._connected:
            self.connect()
        if not self._connected:
            if self._cached_positions:
                logger.warning("⚠️ Tiger 离线，使用缓存持仓")
                return self._cached_positions
            return []

        try:
            positions = self._trade_client.get_positions()
            logger.info(f"🔍 Tiger get_positions: {len(positions) if hasattr(positions, '__len__') else 0} 只")
            
            result = []
            for p in (positions or []):
                # Tiger SDK: Position.contract.symbol, not Position.symbol
                ticker = p.contract.symbol if hasattr(p.contract, 'symbol') else str(p.contract)

                # ★ 货币转换：HK 持仓以 HKD 计价，需转为 USD
                is_hk = ticker.isdigit() and len(ticker) <= 5  # HK ticker: 5-digit number
                fx_rate = trading_config.CURRENCY_RATES.get("HKD", 0.128) if is_hk else 1.0

                result.append({
                    "ticker": ticker,
                    "shares": p.quantity,
                    "avg_cost": float(p.average_cost) * fx_rate,
                    "market_value": float(p.market_value) * fx_rate,
                    "market_price": float(p.market_price) * fx_rate,
                    "realized_pnl": float(p.realized_pnl) * fx_rate,
                    "unrealized_pnl": float(p.unrealized_pnl) * fx_rate,
                    "currency": "HKD" if is_hk else "USD",
                })
            # Save to cache
            self._cached_positions = result
            self._last_positions_call = now
            return result
        except Exception as e:
            logger.error(f"❌ 获取持仓失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            if self._cached_positions:
                return self._cached_positions
            return []

    def get_account_info(self, force: bool = False) -> Optional[Dict]:
        """获取账户信息 — 带缓存避免 API 限流"""
        now = time.time()
        if not force and self._cached_account is not None and (now - self._last_account_call) < self._min_call_interval:
            logger.debug(f"♻️ 使用缓存账户 ({now - self._last_account_call:.0f}s 前)")
            return self._cached_account
        if not self._connected:
            return None

        try:
            assets = self._trade_client.get_assets(account=self._active_account or trading_config.TIGER_ACCOUNT)
            if not assets:
                logger.warning("⚠️ Tiger get_assets 返回空，尝试重连...")
                self.connect()
                assets = self._trade_client.get_assets(account=self._active_account or trading_config.TIGER_ACCOUNT)
            
            if assets and isinstance(assets, list) and len(assets) > 0:
                a = assets[0]
                summary = a.summary if hasattr(a, 'summary') and a.summary else None
                
                # market_value 是方法（需调用），也有 market_values dict
                mkt_val = 0.0
                leverage = 1.0
                gross_position = 0.0
                
                # Try calling market_value() method
                if hasattr(a, 'market_value') and callable(a.market_value):
                    try:
                        mkt_val = a.market_value()
                    except:
                        pass
                elif hasattr(a, 'market_value'):
                    mkt_val = a.market_value
                
                # Extract from segments if available
                if hasattr(a, 'segments') and a.segments:
                    for seg_key, seg in a.segments.items():
                        if hasattr(seg, 'gross_position_value'):
                            gross_position += seg.gross_position_value or 0
                        if hasattr(seg, 'leverage') and seg.leverage:
                            leverage = max(leverage, seg.leverage)
                
                # Fallback: use gross_position_value as market_value
                if mkt_val == 0 and gross_position > 0:
                    mkt_val = gross_position
                
                result = {
                    "account": a.account if hasattr(a, 'account') else "",
                    "cash": summary.cash if summary and hasattr(summary, 'cash') else 0,
                    "market_value": round(mkt_val, 2),
                    "total_value": summary.net_liquidation if summary and hasattr(summary, 'net_liquidation') else 0,
                    "buying_power": summary.buying_power if summary and hasattr(summary, 'buying_power') else 0,
                    "realized_pnl": summary.realized_pnl if summary and hasattr(summary, 'realized_pnl') else 0,
                    "unrealized_pnl": summary.unrealized_pnl if summary and hasattr(summary, 'unrealized_pnl') else 0,
                    "leverage": leverage,
                    "gross_position_value": round(gross_position, 2),
                }
                # Save to cache
                self._cached_account = result
                self._last_account_call = now
                return result
        except Exception as e:
            logger.error(f"❌ 获取账户信息失败: {e}")
        
        if self._cached_account:
            logger.warning("⚠️ Tiger API 失败，使用缓存账户数据")
            return self._cached_account
        return None

    def _get_last_price_fallback(self, ticker: str) -> Optional[float]:
        """从缓存持仓中获取最近价格（盘前/盘后价格不可用时的兜底）"""
        if self._cached_positions:
            for p in self._cached_positions:
                if p.get("ticker") == ticker:
                    mp = p.get("market_price", 0)
                    if mp > 0:
                        return mp
                    # fallback to avg_cost
                    ac = p.get("avg_cost", 0)
                    if ac > 0:
                        return ac
        return None

    # ================================================================
    # 港股整手 (Board Lot) 处理
    # ================================================================

    # 港股每手股数对照表（HKEX 标准，未列出的默认 100 股）
    HK_LOT_SIZES: Dict[str, int] = {
        # 银行
        "00939": 1000, "01288": 1000, "03968": 500,  "02388": 500,
        "00005": 400,  "00011": 100,  "01658": 1000,
        # 保险
        "01299": 100,  "02318": 500,  "02628": 2000,
        # 地产
        "00016": 1000, "00017": 1000, "00012": 500,  "00101": 1000,
        "00960": 1000, "01109": 500,  "00688": 500,
        # 能源
        "00857": 2000, "00883": 1000, "00386": 2000,
        # 科技/互联网
        "00700": 100,  "09988": 100,  "09618": 50,   "09888": 50,
        "09899": 50,   "03690": 100,  "09999": 20,
        # 消费
        "00175": 1000, "00291": 2000, "00027": 500,  "00019": 500,
        # 医疗
        "01099": 400,  "00241": 1000, "01177": 1000, "01093": 2000, "02269": 500,
        # 工业/制造
        "00267": 1000, "00285": 500,  "00669": 100,  "00868": 500,
        "00968": 2000, "00981": 500,  "00823": 100,  "00066": 500,
        # 通讯
        "00941": 500,  "00728": 2000, "00762": 500,
        # 综合
        "00288": 1000, "00001": 500,  "00002": 500,  "00003": 1000,
        "00006": 500,  "00857": 2000, "00388": 100,  "00148": 1000,
        # SG
        "F83": 100, "Z74": 100, "D05": 100, "O39": 100,
    }

    @staticmethod
    def get_hk_lot_size(ticker: str) -> int:
        """获取港股每手股数（整手）"""
        # 去掉后缀
        clean = ticker.replace(".HK", "").replace(".SI", "").strip()
        return TigerClient.HK_LOT_SIZES.get(clean.zfill(5), 100)

    @staticmethod
    def is_lot_market(ticker: str) -> bool:
        """判断是否需要整手交易（港股/新加坡股）"""
        clean = ticker.replace(".HK", "").replace(".SI", "").strip()
        return ticker.endswith(".HK") or ticker.endswith(".SI") or (
            len(clean) <= 5 and clean.isdigit()
        )

    @staticmethod
    def round_to_lot(ticker: str, quantity: int) -> int:
        """将数量取整到整手倍数（港股/新加坡股）"""
        is_lot = TigerClient.is_lot_market(ticker)
        if not is_lot:
            return max(1, int(quantity))  # 美股至少 1 股

        lot = TigerClient.get_hk_lot_size(ticker)
        if quantity < lot:
            return 0  # 不够一手，不买
        return (int(quantity) // lot) * lot

    @staticmethod
    def _align_hk_tick(price: float) -> float:
        """将价格对齐到港股最小变动价位"""
        if price <= 0:
            return price
        # HKEX tick size rules
        tick_rules = [
            (0.25, 0.001), (0.50, 0.005), (2.0, 0.010),
            (5.0, 0.025), (10.0, 0.020), (20.0, 0.050),
            (100.0, 0.100), (200.0, 0.200), (500.0, 0.500),
            (1000.0, 1.000), (2000.0, 2.000), (float("inf"), 5.000),
        ]
        for upper, tick in tick_rules:
            if price < upper:
                return round(price / tick) * tick
        return price

    @staticmethod
    def _align_sg_tick(price: float) -> float:
        """新加坡股票 tick size"""
        if price < 1.0:
            return round(price / 0.001) * 0.001
        elif price < 10.0:
            return round(price / 0.005) * 0.005
        return round(price / 0.01) * 0.01

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

    # ================================================================
    # 全量同步到本地数据库
    # ================================================================

    def sync_all_to_db(self) -> Dict:
        """
        将 Tiger 最新数据全量同步到本地 SQLite 数据库。
        - 持仓、账户、订单历史、实时报价
        - 非阻塞，失败时静默降级

        Returns:
            {"synced": bool, "positions": int, "account": bool, "quotes": int, "orders": int, "error": str}
        """
        result = {"synced": False, "positions": 0, "account": False, "quotes": 0, "orders": 0, "error": ""}
        if not self._connected:
            result["error"] = "not_connected"
            return result

        try:
            from backend.data_engine.historical_store import HistoricalStore
            store = HistoricalStore()
        except Exception as e:
            result["error"] = f"store_init_failed: {e}"
            logger.warning(f"⚠️ sync_all_to_db: HistoricalStore 不可用: {e}")
            return result

        try:
            # 1. 同步持仓
            positions = self.get_positions(force=True)
            if positions:
                for pos in positions:
                    snapshot = {
                        "ticker": pos.get("ticker", ""),
                        "shares": pos.get("shares", 0),
                        "avg_cost": pos.get("avg_cost", 0),
                        "market_value": pos.get("market_value", 0),
                        "market_price": pos.get("market_price", 0),
                        "unrealized_pnl": pos.get("unrealized_pnl", 0),
                        "realized_pnl": pos.get("realized_pnl", 0),
                        "currency": pos.get("currency", "USD"),
                        "timestamp": datetime.now().isoformat(),
                    }
                    store.save_snapshot(snapshot)
                result["positions"] = len(positions)

            # 2. 同步账户信息
            account = self.get_account_info(force=True)
            if account:
                acct_snapshot = {
                    "ticker": "_ACCOUNT_",
                    "cash": account.get("cash", 0),
                    "market_value": account.get("market_value", 0),
                    "total_value": account.get("total_value", 0),
                    "buying_power": account.get("buying_power", 0),
                    "leverage": account.get("leverage", 1.0),
                    "unrealized_pnl": account.get("unrealized_pnl", 0),
                    "realized_pnl": account.get("realized_pnl", 0),
                    "timestamp": datetime.now().isoformat(),
                }
                store.save_snapshot(acct_snapshot)
                result["account"] = True

            # 3. 同步实时报价（对有持仓的股票）
            if positions:
                quote_count = 0
                for pos in positions[:30]:  # 限制 30 只避免超频
                    ticker = pos.get("ticker", "")
                    if not ticker:
                        continue
                    quote = self.get_quote(ticker)
                    if quote and quote.get("price", 0) > 0:
                        store.save_price_ticks_batch({ticker: quote["price"]})
                        quote_count += 1
                result["quotes"] = quote_count

            # 4. 同步当日订单（如有 get_open_orders 方法可用）
            try:
                open_orders = self._trade_client.get_open_orders() if self._trade_client else []
                if open_orders:
                    orders_list = []
                    for o in (open_orders or []):
                        orders_list.append({
                            "order_id": getattr(o, "id", ""),
                            "ticker": getattr(o.contract, "symbol", "") if hasattr(o, "contract") else "",
                            "action": getattr(o, "action", ""),
                            "quantity": getattr(o, "quantity", 0),
                            "status": str(getattr(o, "status", "")),
                            "price": getattr(o, "limit_price", 0) or 0,
                            "timestamp": datetime.now().isoformat(),
                        })
                    if orders_list:
                        store.save_trades_batch(orders_list)
                        result["orders"] = len(orders_list)
            except Exception:
                pass  # 无 open orders 或方法不可用

            result["synced"] = True
            logger.debug(f"📥 sync_all_to_db: {result['positions']} 持仓, 账户{'✓' if result['account'] else '✗'}, "
                         f"{result['quotes']} 报价, {result['orders']} 订单")
        except Exception as e:
            result["error"] = str(e)
            logger.warning(f"⚠️ sync_all_to_db 失败: {e}")

        return result


# 全局单例
tiger_client = TigerClient()
