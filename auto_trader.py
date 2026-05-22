"""
自动交易引擎 v2 - 全市场版
- 监控 500+ 美股 + 100+ 港股
- 分层扫描：每5分钟快速扫描 + 每30分钟全量刷新
- AI 分析聚焦 Top 候选 + 持仓
- 风控 + 老虎下单
"""
import os, sys, time, json
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

logger.add("logs/auto_trader_{time}.log", rotation="1 day", retention="30 days")


class AutoTrader:
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

        if self.portfolio.load_state():
            self.risk.portfolio_value = self.portfolio.total_value
            self.risk.cash = self.portfolio.cash
            self.risk.positions = dict(self.portfolio.positions)
            self.risk.peak_value = max(self.portfolio.total_value, trading_config.INITIAL_CAPITAL)
            logger.info(f"✅ 已恢复持仓: {len(self.portfolio.positions)} 只, 现金 ${self.portfolio.cash:.2f}")
        else:
            logger.info("📝 无历史持仓")

        self.strategy = TradingStrategy(
            self.transformer, self.rl_agent,
            self.sentiment, self.ensemble, self.executor
        )

        # 老虎证券
        self.tiger_ready = tiger_client.connect()
        logger.info(f"老虎: {'✅已连接' if self.tiger_ready else '⚠️未连接'}")

        # === 全市场股票池 ===
        logger.info("🏗️ 构建全市场股票池...")
        stock_universe.build(force=False)  # 优先用缓存
        self.universe_tickers = stock_universe.all_tickers
        logger.info(f"📊 股票池: {len(self.universe_tickers)} 只 (US {len(stock_universe.us_tickers)} + HK {len(stock_universe.hk_tickers)})")

        self.cycle = 0
        self.full_scan_cycle = 0
        self.batch_size = 30  # 每批获取的股票数

    @property
    def position_tickers(self) -> list:
        """当前持仓股票"""
        return list(self.portfolio.positions.keys())

    def _get_candidate_tickers(self) -> list:
        """获取本轮要分析的候选股票：持仓 + 高波动Top"""
        candidates = set(self.position_tickers)

        # 加入高波动候选
        volatile = stock_universe.get_high_volatility(n=20)
        for s in volatile:
            t = s.get("ticker", "")
            if isinstance(t, str) and t:
                candidates.add(t)

        # 加入 Top 市值（分散行业）
        top = stock_universe.get_top_by("market_cap", n=15)
        for s in top:
            t = s.get("ticker", "")
            if isinstance(t, str) and t:
                candidates.add(t)

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

    def run_cycle(self):
        """执行一次交易循环"""
        self.cycle += 1
        start = time.time()
        logger.info(f"\n{'='*50}\n  Cycle #{self.cycle} - {datetime.now().strftime('%H:%M:%S')}\n{'='*50}")

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
        if result.get("trades"):
            for trade in result["trades"]:
                logger.info(f"  📊 交易: {trade['ticker']} {trade['side']} {trade['quantity']:.2f}股")
            self.portfolio.save_state()
            self.risk.update_portfolio_state(
                self.portfolio.total_value,
                self.portfolio.cash,
                self.portfolio.positions,
                prices
            )
        elif result.get("signals"):
            self.risk.update_portfolio_state(
                self.portfolio.total_value,
                self.portfolio.cash,
                self.portfolio.positions,
                prices
            )

        # 5. 持仓检查
        if self.portfolio.positions:
            mv = sum(
                shares * self.portfolio.avg_costs.get(t, 0)
                for t, shares in self.portfolio.positions.items()
            )
            tv = self.portfolio.cash + mv
            pnl = tv - trading_config.INITIAL_CAPITAL
            pnl_pct = (pnl / trading_config.INITIAL_CAPITAL) * 100
            logger.info(f"💰 资产: ${tv:,.0f} | 盈亏: {pnl:+,.0f} ({pnl_pct:+.1f}%) | 现金: ${self.portfolio.cash:,.0f}")

        elapsed = time.time() - start
        logger.info(f"⏱  Cycle #{self.cycle} 完成 (耗时 {elapsed:.1f}s)")

        return result

    def start(self, interval_seconds=300):
        """开始自动循环"""
        logger.info(f"\n🚀 全市场自动交易引擎启动")
        logger.info(f"   全市场: {len(self.universe_tickers)} 只")
        logger.info(f"   每轮分析: ~{self.batch_size} 只")
        logger.info(f"   间隔: {interval_seconds}s ({interval_seconds//60}min)")
        logger.info(f"   老虎: {'模拟' if not self.tiger_ready else '✅已连接'}")

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
