"""
自动交易引擎 v2.1 - 全市场版
- 监控 500+ 美股 + 100+ 港股
- 分层扫描：每5分钟快速扫描 + 每30分钟全量刷新
- AI 分析聚焦 Top 候选 + 持仓
- 风控 + 老虎下单
- P0-2: 集成组合级熔断机制
"""
import os, sys, time, json, random
from datetime import datetime
from pathlib import Path

PROJ_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJ_ROOT))

from loguru import logger
from backend.config import data_config, trading_config
from backend.data_engine import MarketDataEngine, DataPipeline
from backend.data_engine.tiger_client import tiger_client
from backend.data_engine.stock_universe import stock_universe
from backend.ai_models import TransformerPredictor, TradingRLAgent, SentimentAnalyzer, SignalEnsemble
from backend.ai_models.trainer import ModelTrainer
from backend.trading_engine import PaperExecutor, RiskManager, PortfolioManager
from backend.trading_engine.strategy import TradingStrategy
from backend.data_engine.data_pipeline import DataPipeline

pipeline = DataPipeline()

# 沙箱兼容：用 shell 重定向接管日志写入，避免 PermissionError
# logger.add("logs/auto_trader_{time}.log", rotation="1 day", retention="30 days")


class AutoTrader:
    """全市场自动交易引擎 v2.1 — 集成 P0-2 熔断机制"""

    def __init__(self):
        self.market = MarketDataEngine()
        self.pipeline = DataPipeline()
        self.trainer = ModelTrainer()

        # 加载模型
        logger.info("加载 AI 模型...")
        self.transformer = TransformerPredictor()
        self.rl_agent = TradingRLAgent()
        self.sentiment = SentimentAnalyzer()
        self.ensemble = SignalEnsemble()

        if self.transformer.load():
            logger.info("✅ Transformer 模型已加载")
        else:
            logger.warning("⚠️ Transformer 模型未找到")
        if self.rl_agent.load():
            logger.info("✅ RL Agent 模型已加载")
        else:
            logger.warning("⚠️ RL Agent 模型未找到")

        # 交易组件
        self.portfolio = PortfolioManager(trading_config.INITIAL_CAPITAL)
        self.risk = RiskManager()
        self.executor = PaperExecutor(self.portfolio, self.risk)

        # 先加载本地状态作为 fallback
        local_state = self.portfolio.load_state()
        if local_state:
            logger.info(f"✅ 本地已恢复持仓: {len(self.portfolio.positions)} 只, 现金 ${self.portfolio.cash:.2f}")
        else:
            logger.info("📝 无历史持仓")

        # 老虎证券连接
        self.tiger_ready = tiger_client.connect()
        logger.info(f"老虎: {'✅已连接' if self.tiger_ready else '⚠️未连接'}")

        # ★ 关键：Tiger 连接成功后，从老虎同步真实持仓（覆盖本地状态）
        if self.tiger_ready:
            logger.info("🔄 从老虎证券同步真实持仓...")
            self.portfolio._tiger_initial_capital_synced = False  # ★ 强制重置
            sync_result = self.portfolio.sync_from_tiger(force=True)
            if sync_result["synced"]:
                logger.info(
                    f"✅ Tiger 同步成功: {sync_result['positions']} 只持仓, "
                    f"现金 ${sync_result['cash']:,.2f}, 总资产 ${sync_result['total_value']:,.2f}"
                )
            else:
                logger.warning(f"⚠️ Tiger 同步未完成: {sync_result['source']}")
                if not local_state:
                    logger.info("使用默认初始资金 $1,000,000")

        # ★ 修复：Tiger 同步后，将 trading_config.INITIAL_CAPITAL 校准为实际账户值
        # 避免 $1M 默认值导致风控系统误判 99% 回撤
        if self.tiger_ready:
            trading_config.INITIAL_CAPITAL = self.portfolio.initial_capital
            logger.info(f"📐 INITIAL_CAPITAL 已校准: ${trading_config.INITIAL_CAPITAL:,.2f}")

        # 更新风控状态（基于最新 PortfolioManager 状态）
        self.risk.portfolio_value = self.portfolio.total_value
        self.risk.cash = self.portfolio.cash
        self.risk.positions = dict(self.portfolio.positions)
        self.risk.peak_value = self.portfolio.total_value

        # P0-2: 初始化当日起始净值为当前资产
        self.risk.daily_start_value = self.portfolio.total_value
        logger.info(f"📅 当日起始净值: ${self.risk.daily_start_value:,.2f}")

        self.strategy = TradingStrategy(
            self.transformer, self.rl_agent,
            self.sentiment, self.ensemble, self.executor
        )

        # === 全市场股票池 ===
        logger.info("🏗️ 构建全市场股票池...")
        stock_universe.build(force=False)  # 优先用缓存
        self.universe_tickers = stock_universe.all_tickers
        logger.info(f"📊 股票池: {len(self.universe_tickers)} 只 (US {len(stock_universe.us_tickers)} + HK {len(stock_universe.hk_tickers)})")

        self.cycle = 0
        self.full_scan_cycle = 0
        self.batch_size = 50  # 每批获取的股票数

        # 每日交易限制
        self.trades_today = 0
        self.trade_date = datetime.now().strftime("%Y-%m-%d")
        self.max_daily_trades = trading_config.MAX_DAILY_TRADES
        logger.info(f"📊 每日交易上限: {self.max_daily_trades} 笔")

        # P0-2: 熔断状态
        self._circuit_broken = False

        # ★ 强制卖出列表（启动时清仓指定持仓）
        self._force_sell_positions: dict = {}
        if self.tiger_ready and self.portfolio.positions:
            # 将所有现有持仓加入强制卖出列表
            for ticker, shares in list(self.portfolio.positions.items()):
                self._force_sell_positions[ticker] = shares
            logger.info(f"📋 强制卖出列表: {self._force_sell_positions}")

        # ★ 无杠杆标记
        self._leverage_blocked = False

    # ================================================================
    # 市场时段检查
    # ================================================================

    @staticmethod
    def _is_market_open() -> dict:
        """检查各市场是否在交易时段（含盘前/盘后/夜盘）"""
        import pytz
        now = datetime.now()
        result = {"US": False, "HK": False, "US_regular": False, "US_extended": False}

        try:
            # US: 支持盘前(4:00-9:30) + 正常(9:30-16:00) + 盘后(16:00-20:00) ET
            # Tiger API outside_rth=True 覆盖全部扩展时段
            us_tz = pytz.timezone('US/Eastern')
            us_now = now.astimezone(us_tz)
            if us_now.weekday() < 5:
                us_hour = us_now.hour + us_now.minute / 60
                # 正常时段: 9:30-16:00
                result["US_regular"] = 9.5 <= us_hour < 16.0
                # 扩展时段: 盘前 4:00-9:30 + 盘后 16:00-20:00
                result["US_extended"] = (4.0 <= us_hour < 9.5) or (16.0 <= us_hour < 20.0)
                # 总交易时段（含夜盘支持）
                result["US"] = 4.0 <= us_hour < 20.0
        except Exception:
            pass

        try:
            # HK: 9:30-16:00 HKT (Mon-Fri)
            hk_tz = pytz.timezone('Asia/Hong_Kong')
            hk_now = now.astimezone(hk_tz)
            if hk_now.weekday() < 5:
                hk_open = hk_now.replace(hour=9, minute=30, second=0)
                hk_close = hk_now.replace(hour=16, minute=0, second=0)
                result["HK"] = hk_open <= hk_now <= hk_close
        except Exception:
            pass

        return result

    def _sync_tiger_state(self):
        """实时同步 Tiger 真实资产数据 → 本地 Portfolio + Risk + Backend"""
        try:
            sync_result = self.portfolio.sync_from_tiger(force=True)
            if sync_result.get("synced"):
                self.risk.portfolio_value = self.portfolio.total_value
                self.risk.cash = self.portfolio.cash
                self.risk.positions = dict(self.portfolio.positions)
                # ★ FIX: 同步 peak_value 和 daily_start_value，防止误触发熔断
                # 只有当 Tiger 总资产高于本地峰值时才调高 peak（不降低峰值的铁律）
                if self.portfolio.total_value > self.risk.peak_value:
                    self.risk.peak_value = self.portfolio.total_value
                # 同样：Tiger 同步后校准 daily_start_value
                if self.portfolio.total_value > self.risk.daily_start_value:
                    self.risk.daily_start_value = self.portfolio.total_value
                # 推送实时数据到前端看板
                self._push_tiger_snapshot()
        except Exception as e:
            logger.warning(f"⚠️ Tiger实时同步异常: {e}")

    def _push_tiger_snapshot(self):
        """推送 Tiger 实时快照到后端 WebSocket"""
        try:
            import requests
            payload = {
                "portfolio_value": self.portfolio.total_value,
                "cash": self.portfolio.cash,
                "positions": {
                    t: {
                        "shares": round(s, 2),
                        "avg_cost": round(self.portfolio.avg_costs.get(t, 0), 4),
                    }
                    for t, s in self.portfolio.positions.items()
                },
                "pnl": self.portfolio.total_value - trading_config.INITIAL_CAPITAL,
                "pnl_pct": (self.portfolio.total_value / max(trading_config.INITIAL_CAPITAL, 1) - 1) * 100,
            }
            requests.post(
                "http://localhost:8001/api/push/tiger-snapshot",
                json=payload, timeout=3,
            )
        except Exception:
            pass  # 静默失败，不影响交易

    @property
    def position_tickers(self) -> list:
        """当前持仓股票"""
        return list(self.portfolio.positions.keys())

    def _get_candidate_tickers(self) -> list:
        """获取本轮要分析的候选股票：持仓 + 高波动Top + 各市场分散"""
        candidates = set(self.position_tickers)

        # 加入高波动候选（扩容后增加）
        volatile = stock_universe.get_high_volatility(n=35)
        for s in volatile:
            t = s.get("ticker", "")
            if isinstance(t, str) and t:
                candidates.add(t)

        # 加入 Top 市值（分散行业和市场）
        top = stock_universe.get_top_by("market_cap", n=25)
        for s in top:
            t = s.get("ticker", "")
            if isinstance(t, str) and t:
                candidates.add(t)

        # 确保美股/港股/新加坡股都有代表
        for market_suffix, count in [("", 5), (".HK", 5), (".SI", 3)]:
            market_stocks = [s.get("ticker","") for s in stock_universe._all_stocks
                           if isinstance(s, dict) and s.get("ticker","").endswith(market_suffix) if market_suffix
                           or (isinstance(s, dict) and not any(x in s.get("ticker","") for x in [".HK",".SI",".AX",".NZ"]))]
            if len(market_stocks) > count:
                market_stocks = random.sample(market_stocks, count)
            candidates.update(market_stocks)

        # 限制总数，优先持仓
        tickers = list(candidates)
        pos_tickers = set(self.position_tickers)
        tickers.sort(key=lambda t: 0 if t in pos_tickers else 1)
        return tickers[:self.batch_size]

    def _fetch_batch_data(self, tickers: list) -> dict:
        """批量获取数据并处理"""
        data_dict = {}
        prices = {}
        errors = 0

        for ticker in tickers:
            try:
                df = self.market.get_historical_data(ticker, period="2y", interval="1d")
                if df is not None and not df.empty:
                    processed = self.pipeline.process(df)
                    if processed is not None:
                        fcols = [c for c in pipeline.FEATURE_COLUMNS if c in processed.columns]
                        if len(fcols) >= 30:
                            data_dict[ticker] = {"features": processed[fcols].values}
                    price_col = 'Close' if 'Close' in df.columns else 'close'
                    prices[ticker] = float(df[price_col].iloc[-1])
                else:
                    errors += 1
            except Exception:
                errors += 1
                continue

        return data_dict, prices, errors

    def _update_portfolio_valuation(self):
        """仅更新持仓估值，不执行新交易（达到每日上限时使用）"""
        try:
            tickers = self._get_candidate_tickers()
            _, prices, _ = self._fetch_batch_data(tickers)
            if prices:
                self.portfolio.update_value(prices)
                self.risk.update_portfolio_state(
                    self.portfolio.total_value,
                    self.portfolio.cash,
                    self.portfolio.positions,
                    prices
                )
        except Exception:
            pass

    # ================================================================
    # P0-2: 熔断检查与平仓
    # ================================================================

    def _check_circuit_breaker_and_liquidate(self, prices: dict) -> bool:
        """
        P0-2: 检查熔断状态，若触发则自动平仓所有持仓。

        Args:
            prices: {ticker: price} 当前价格字典

        Returns:
            True 如果熔断已触发（本轮应跳过交易），False 表示正常
        """
        cb_report = self.risk.check_circuit_breaker()

        if cb_report.circuit_breaker:
            if not self._circuit_broken:
                # 首次触发 — 立即平仓
                logger.error("🚨🚨🚨 熔断触发！执行组合级平仓 🚨🚨🚨")
                liquidation_records = self.risk.liquidate_all(prices)
                # 同步平仓到 PortfolioManager
                for record in liquidation_records:
                    self.portfolio.positions[record["ticker"]] = 0.0
                self.portfolio.cash = self.risk.cash
                self.portfolio.save_state()
                self._circuit_broken = True
                logger.error(
                    f"🚨 平仓完成: {len(liquidation_records)} 笔, "
                    f"现金=${self.risk.cash:,.2f}"
                )
            else:
                logger.warning("🚨 熔断持续中 — 跳过交易，仅更新估值")

            return True  # 熔断中，跳过本轮交易

        # 熔断未触发 / 冷却期结束
        if self._circuit_broken:
            logger.info("🟢 熔断状态解除，恢复正常交易")
            self._circuit_broken = False

        return False

    def run_cycle(self):
        """执行一次交易循环"""
        self.cycle += 1
        start = time.time()

        # ★ P0-2: 新交易日检测并重置
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self.trade_date:
            self.trades_today = 0
            self.trade_date = today
            self.risk.reset_daily_state()
            logger.info(f"📅 新交易日 {today}，重置交易计数和熔断状态")

        # ★ 每轮交易前从 Tiger 实时同步资产数据
        if self.tiger_ready:
            self._sync_tiger_state()

        # ★ P0-1: 无杠杆铁律 — 每轮交易前强制检查
        if self.tiger_ready:
            try:
                tiger_acct = tiger_client.get_account_info()
                if tiger_acct:
                    leverage = tiger_acct.get("leverage", 1.0)
                    margin = tiger_acct.get("margin", 0)
                    total_assets = tiger_acct.get("total_value", 0)
                    if leverage > 1.001 or margin > 0:
                        logger.error(
                            f"🚨🚨🚨 杠杆铁律触发！本轮跳过所有买入 🚨🚨🚨\n"
                            f"   Tiger杠杆率: {leverage:.4f} (>1.0 说明借钱)\n"
                            f"   融资余额: ${margin:,.2f}\n"
                            f"   总资产: ${total_assets:,.2f}\n"
                            f"   处理: 跳过全部买入，等待杠杆清零后恢复"
                        )
                        self._leverage_blocked = True
                    else:
                        if getattr(self, '_leverage_blocked', False):
                            logger.info("🟢 杠杆已清零，恢复正常买入")
                        self._leverage_blocked = False
            except Exception as e:
                logger.warning(f"⚠️ 杠杆检查异常: {e}")

        # ★ 每日交易限制：上限检查（0 = 不限制）
        if self.max_daily_trades > 0 and self.trades_today >= self.max_daily_trades:
            logger.info(
                f"⏸  今日交易已达上限 ({self.trades_today}/{self.max_daily_trades})，"
                f"跳过交易，仅更新持仓估值"
            )
            self._update_portfolio_valuation()
            return

        logger.info(
            f"\n{'='*50}\n  Cycle #{self.cycle} - {datetime.now().strftime('%H:%M:%S')}"
            f" | 今日: {self.trades_today}/{self.max_daily_trades} 笔\n{'='*50}"
        )

        # 每 6 个周期（30分钟）全量刷新股票池排名
        if self.cycle % 6 == 1:
            self.full_scan_cycle += 1
            logger.info(f"🔄 全量刷新 #{self.full_scan_cycle}...")
            stock_universe.build(force=False)

        # 1. 获取候选股票池
        tickers = self._get_candidate_tickers()
        pos_count = len([t for t in tickers if t in self.position_tickers])
        logger.info(f"🔍 分析 {len(tickers)} 只 (持仓 {pos_count} + 候选 {len(tickers)-pos_count}) | 全市场 {len(self.universe_tickers)} 只")

        # 2. 批量获取数据
        data_dict, prices, errors = self._fetch_batch_data(tickers)
        logger.info(f"数据: {len(data_dict)}/{len(tickers)} 成功, {errors} 失败")

        if len(data_dict) < 2:
            logger.warning("数据不足，跳过本轮")
            return

        # ★ P0-2: 熔断检查（在交易前执行）
        if self._check_circuit_breaker_and_liquidate(prices):
            # 熔断中，仅推送估值更新
            self._push_to_backend({"signals": {}, "trades": []}, prices)
            return

        # ★ 强制卖出（清仓指定持仓）— 支持盘前/盘后
        if self._force_sell_positions:
            for ticker, shares in list(self._force_sell_positions.items()):
                current_price = prices.get(ticker, 0)
                # 无价格时尝试从 Tiger 实时获取（盘前/盘后数据源不可靠）
                if current_price <= 0 and self.tiger_ready:
                    quote = tiger_client.get_quote(ticker)
                    if quote and quote.get("price", 0) > 0:
                        current_price = quote["price"]
                        prices[ticker] = current_price
                        logger.info(f"📡 Tiger实时价: {ticker} ${current_price:.2f}")
                if current_price <= 0:
                    logger.debug(f"⏸ 强制卖出暂缺价格: {ticker}")
                    continue
                logger.info(f"🔨 强制卖出: {ticker} {shares:.0f}股 @ ${current_price:.2f}")
                trade = self.executor.execute_signal(
                    ticker=ticker, decision="sell", strength=1.0,
                    price=current_price, confidence=1.0, strategy="force_sell"
                )
                if trade:
                    logger.info(f"✅ 强制卖出成功: {ticker} {trade['quantity']:.0f}股")
                    del self._force_sell_positions[ticker]
                    self.trades_today += 1
                else:
                    logger.warning(f"⏸ 强制卖出暂未执行: {ticker}（可能市场休市或风控拒绝）")

        # 3. AI 分析
        logger.info("AI 模型分析中...")
        try:
            result = self.strategy.analyze_and_trade(
                [t for t in tickers if t in data_dict],
                data_dict, prices
            )
        except Exception as e:
            logger.error(f"分析失败: {e}")
            return

        signals = self.strategy.last_signals

        # 统计
        buys = sum(1 for s in signals.values() if s.get("decision") == "buy")
        sells = sum(1 for s in signals.values() if s.get("decision") == "sell")
        holds = sum(1 for s in signals.values() if s.get("decision") == "hold")
        logger.info(f"信号: {buys}买 {sells}卖 {holds}持")

        # Top 信号
        for ticker, s in sorted(signals.items(), key=lambda x: x[1].get("strength", 0), reverse=True)[:12]:
            if s.get("strength", 0) > 0.3:
                logger.info(
                    f"  {s['decision'].upper():5s} {ticker:8s} "
                    f"强度:{s.get('strength',0):.1%} 置信:{s.get('confidence',0):.1%}"
                )

        # 4. 执行交易
        # ★ 无杠杆铁律：杠杆阻塞时跳过所有买入
        if getattr(self, '_leverage_blocked', False) and result.get("trades"):
            blocked_buys = [t for t in result["trades"] if t.get("side") == "buy"]
            result["trades"] = [t for t in result["trades"] if t.get("side") != "buy"]
            if blocked_buys:
                logger.warning(
                    f"🚫 杠杆铁律拦截: {len(blocked_buys)} 笔买入已阻止 "
                    f"({', '.join(t['ticker'] for t in blocked_buys[:5])}...)"
                )

        if result.get("trades"):
            trade_count = len(result["trades"])
            for trade in result["trades"]:
                logger.info(f"  📊 交易: {trade['ticker']} {trade['side']} {trade['quantity']:.2f}股")
            self.trades_today += trade_count
            logger.info(f"  📈 今日累计: {self.trades_today}/{self.max_daily_trades} 笔")
            self.portfolio.save_state()
            self.risk.update_portfolio_state(
                self.portfolio.total_value,
                self.portfolio.cash,
                self.portfolio.positions,
                prices
            )

            # ★ 交易后立即从 Tiger 同步真实数据
            if self.tiger_ready:
                self._sync_tiger_state()
        elif result.get("signals"):
            self.risk.update_portfolio_state(
                self.portfolio.total_value,
                self.portfolio.cash,
                self.portfolio.positions,
                prices
            )

        # 5. P0-2: 交易后再次检查熔断（新交易可能触发亏损）
        self._check_circuit_breaker_and_liquidate(prices)

        # 6. 持仓检查
        if self.portfolio.positions:
            mv = sum(
                shares * self.portfolio.avg_costs.get(t, 0)
                for t, shares in self.portfolio.positions.items()
            )
            tv = self.portfolio.cash + mv
            pnl = tv - trading_config.INITIAL_CAPITAL
            pnl_pct = (pnl / trading_config.INITIAL_CAPITAL) * 100
            daily_pnl = self.risk.get_daily_pnl()
            logger.info(f"💰 资产: ${tv:,.0f} | 日盈亏: ${daily_pnl:+,.0f} | 总盈亏: {pnl:+,.0f} ({pnl_pct:+.1f}%) | 现金: ${self.portfolio.cash:,.0f}")

        elapsed = time.time() - start
        logger.info(f"⏱  Cycle #{self.cycle} 完成 (耗时 {elapsed:.1f}s)")

        # 7. Tiger 空头/杠杆自动修复（已有实时同步，此处仅做异常修复）
        if self.tiger_ready:
            try:
                # 空头(负持仓)自动修复
                neg_count = sum(1 for s in self.portfolio.positions.values() if s < 0)
                if neg_count > 0:
                    logger.warning(f"⚠️ 发现 {neg_count} 个负持仓(空头)！立即买回修复...")
                    for ticker, neg_shares in list(self.portfolio.positions.items()):
                        if neg_shares >= 0:
                            continue
                        buy_qty = abs(neg_shares)
                        logger.info(f"  🔄 空头修复: {ticker} 买入 {buy_qty:.0f} 股")
                        buy_price = prices.get(ticker) if prices else None
                        if buy_price and buy_price > 0:
                            self.executor.execute_signal(
                                ticker=ticker, decision="buy",
                                strength=min(0.5, buy_qty * buy_price / (self.portfolio.cash * 0.5 + 1)),
                                price=buy_price, confidence=0.5
                            )
                    self.portfolio.save_state()
                    logger.info("✅ 空头修复完成")
            except Exception as e:
                logger.error(f"Tiger 修复异常: {e}")

        # 8. 推送数据到后端 WebSocket + 自动持久化
        self._push_to_backend(result, prices)

        return result

    def _push_to_backend(self, result: dict, prices: dict):
        """推送周期数据到后端，实现实时前端更新"""
        try:
            import requests
            payload = {
                "prices": {t: round(p, 4) for t, p in prices.items()},
                "signals": self.strategy.last_signals,
                "trades": result.get("trades", []),
                "portfolio": {
                    "total_value": self.portfolio.total_value,
                    "cash": self.portfolio.cash,
                    "total_pnl": self.portfolio.total_value - trading_config.INITIAL_CAPITAL,
                    "num_positions": len(self.portfolio.positions),
                },
                "risk": {
                    "circuit_breaker_triggered": self.risk.circuit_breaker_triggered,
                    "daily_pnl": self.risk.get_daily_pnl(),
                    "current_drawdown": self.risk.get_current_drawdown(),
                },
            }
            requests.post(
                "http://localhost:8001/api/push/cycle-data",
                json=payload,
                timeout=5,
            )
        except Exception:
            pass  # 静默失败，不阻塞交易循环

    def start(self, interval_seconds=300):
        """开始自动循环"""
        mk_status = self._is_market_open()
        us_status = "🟢盘前" if mk_status["US_extended"] and not mk_status["US_regular"] else ("🟢盘中" if mk_status["US_regular"] else ("🟢盘后" if mk_status["US_extended"] else "🔴休市"))
        logger.info(f"\n🚀 全市场自动交易引擎 v2.1 启动")
        logger.info(f"   全市场: {len(self.universe_tickers)} 只")
        logger.info(f"   每轮分析: ~{self.batch_size} 只")
        logger.info(f"   间隔: {interval_seconds}s ({interval_seconds//60}min)")
        logger.info(f"   熔断: 日亏≥{trading_config.DAILY_LOSS_LIMIT:.0%}, 冷却{trading_config.CIRCUIT_BREAKER_COOLDOWN}s")
        logger.info(f"   老虎实盘: {'✅已连接' if self.tiger_ready else '⚠️未连接'}")
        logger.info(f"   🚫 杠杆政策: 全球股票一律不加杠杆 (NO_LEVERAGE=ON)")
        logger.info(f"   市场状态: 美股{us_status}, 港股{'🟢' if mk_status['HK'] else '🔴'}")
        if self._force_sell_positions:
            logger.info(f"   📋 待强制卖出: {list(self._force_sell_positions.keys())}")

        while True:
            try:
                self.run_cycle()
            except KeyboardInterrupt:
                logger.info("\n⏹  收到停止信号，关闭引擎...")
                break
            except Exception as e:
                import traceback
                logger.error(f"❌ Cycle #{self.cycle} 异常: {e}")
                logger.error(traceback.format_exc())
                retry_wait = 60
                logger.info(f"休眠 {retry_wait}s 后重试...")
                time.sleep(retry_wait)
                continue

            logger.info(f"休眠 {interval_seconds//60} 分钟...")
            time.sleep(interval_seconds)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=300, help="循环间隔(秒)")
    parser.add_argument("--once", action="store_true", help="只运行一次")
    parser.add_argument("--build", action="store_true", help="强制重建股票池")
    args = parser.parse_args()

    if args.build:
        stock_universe.build(force=True)
        print(f"股票池: {stock_universe.summary()['total']} 只")

    trader = AutoTrader()

    if args.once:
        trader.run_cycle()
    else:
        trader.start(args.interval)
