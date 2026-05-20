"""
自动交易引擎 - 定时循环
- 获取美股港股实时行情
- AI 模型推理 → 信号融合
- 风控检查 → 老虎证券下单
- 绩效追踪 + 日志记录
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
from backend.ai_models import TransformerPredictor, TradingRLAgent, SentimentAnalyzer, SignalEnsemble
from backend.ai_models.trainer import ModelTrainer
from backend.trading_engine import PaperExecutor, RiskManager, PortfolioManager
from backend.trading_engine.strategy import TradingStrategy

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
        
        # 交易组件
        self.portfolio = PortfolioManager(trading_config.INITIAL_CAPITAL)
        self.risk = RiskManager()
        self.executor = PaperExecutor(self.portfolio, self.risk)
        
        # 策略引擎
        self.strategy = TradingStrategy(
            self.transformer, self.rl_agent,
            self.sentiment, self.ensemble, self.executor
        )
        
        # 老虎证券
        self.tiger_ready = tiger_client.connect()
        if self.tiger_ready:
            logger.info("✅ 老虎证券已连接")
        else:
            logger.info("⚠️ 老虎证券未连接，使用模拟模式")
        
        self.cycle = 0
        self.daily_pnl = 0.0
        
    def run_cycle(self):
        """执行一次交易循环"""
        self.cycle += 1
        start = time.time()
        logger.info(f"\n{'='*50}\n  Cycle #{self.cycle} - {datetime.now().strftime('%H:%M:%S')}\n{'='*50}")
        
        # 1. 获取市场数据
        tickers = data_config.ALL_TICKERS
        logger.info(f"获取 {len(tickers)} 只股票数据...")
        
        data_dict = {}
        prices = {}
        errors = 0
        
        for ticker in tickers:
            try:
                df = self.market.get_historical_data(ticker, period="5d", interval="1h")
                if df is not None and not df.empty:
                    processed = self.pipeline.process(df)
                    if processed is not None:
                        data_dict[ticker] = {"features": processed.values}
                    price_col = 'Close' if 'Close' in df.columns else 'close'
                    prices[ticker] = float(df[price_col].iloc[-1])
                else:
                    errors += 1
            except Exception as e:
                errors += 1
                continue
        
        logger.info(f"数据: {len(data_dict)}/{len(tickers)} 成功, {errors} 失败")
        
        if len(data_dict) < 3:
            logger.warning("数据不足，跳过本轮")
            return
        
        # 2. AI 分析
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
        
        # 统计信号
        buys = sum(1 for s in signals.values() if s.get("decision") == "buy")
        sells = sum(1 for s in signals.values() if s.get("decision") == "sell")
        holds = sum(1 for s in signals.values() if s.get("decision") == "hold")
        logger.info(f"信号: {buys}买 {sells}卖 {holds}持")
        
        # 输出 strong signals
        for ticker, s in sorted(signals.items(), key=lambda x: x[1].get("strength", 0), reverse=True):
            if s.get("strength", 0) > 0.3:
                logger.info(
                    f"  {s['decision'].upper():5s} {ticker:6s} "
                    f"强度:{s.get('strength',0):.1%} "
                    f"置信:{s.get('confidence',0):.1%} "
                    f"仓位:{s.get('position_size',0):.1%}"
                )
        
        # 3. 执行交易
        if result.get("trades"):
            for trade in result["trades"]:
                logger.info(f"  📊 交易: {trade}")
        
        # 4. 绩效
        elapsed = time.time() - start
        logger.info(f"⏱  Cycle #{self.cycle} 完成 (耗时 {elapsed:.1f}s)")
        
        return result
    
    def start(self, interval_seconds=1800):
        """开始自动循环
        Args:
            interval_seconds: 循环间隔（秒），默认30分钟
        """
        logger.info(f"\n🚀 自动交易引擎启动")
        logger.info(f"   标的: {len(data_config.ALL_TICKERS)} 只股票")
        logger.info(f"   间隔: {interval_seconds}s ({interval_seconds//60}min)")
        logger.info(f"   老虎: {'模拟' if not self.tiger_ready else '✅已连接'}")
        
        try:
            while True:
                try:
                    self.run_cycle()
                except Exception as e:
                    logger.error(f"Cycle error: {e}")
                
                # 等待下一轮
                logger.info(f"休眠 {interval_seconds//60} 分钟...")
                time.sleep(interval_seconds)
        except KeyboardInterrupt:
            logger.info("\n⏹  收到停止信号，关闭引擎...")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=1800, help="循环间隔(秒)")
    parser.add_argument("--once", action="store_true", help="只运行一次")
    args = parser.parse_args()
    
    trader = AutoTrader()
    
    if args.once:
        trader.run_cycle()
    else:
        trader.start(args.interval)
