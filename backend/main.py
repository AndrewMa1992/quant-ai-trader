"""
Quant AI Trader - FastAPI 主入口
WebSocket 实时推送 + REST API + 定时任务
"""
import asyncio
import json
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Dict, List, Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from backend.config import api_config, data_config, trading_config
from backend.data_engine import MarketDataEngine, DataPipeline
from backend.data_engine.realtime import RealtimeEngine
from backend.data_engine.historical_store import HistoricalStore
from backend.ai_models import (
    TransformerPredictor, TradingRLAgent,
    SentimentAnalyzer, SignalEnsemble, ModelTrainer,
)
from backend.trading_engine import (
    PortfolioManager, RiskManager, PaperExecutor,
    TradingStrategy, Backtester,
)
from backend.data_engine.tiger_client import TigerClient, tiger_client
from backend.api import (
    routes_data, routes_trade, routes_analysis, routes_models
)


# ================================================================
# 全局组件
# ================================================================

market_data = MarketDataEngine()
data_pipeline = DataPipeline()
store = HistoricalStore()

transformer = TransformerPredictor()
rl_agent = TradingRLAgent()
sentiment = SentimentAnalyzer()
ensemble = SignalEnsemble()

portfolio = PortfolioManager()
risk_manager = RiskManager()
executor = PaperExecutor(portfolio, risk_manager)
strategy_engine = TradingStrategy(transformer, rl_agent, sentiment, ensemble, executor)
backtester = Backtester()
trainer = ModelTrainer()

realtime = RealtimeEngine(market_data, data_pipeline)

# WebSocket 连接管理
active_connections: Set[WebSocket] = set()


# ================================================================
# 生命周期
# ================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("Quant AI Trader 启动中...")

    # 初始化路由
    routes_trade.init(executor, portfolio, risk_manager, store)
    routes_analysis.init(strategy_engine, ensemble, backtester)
    routes_models.init(trainer)

    # 尝试加载模型（使用 trainer 做统一加载）
    trans_ready, rl_ready = trainer.load_or_retrain()
    logger.info(f"模型加载: Transformer={'就绪' if trans_ready else '未训练'}, RL={'就绪' if rl_ready else '未训练'}")
    if not trans_ready or not rl_ready:
        logger.info("模型未训练，后台启动训练...")
        import threading
        t = threading.Thread(target=trainer.train_all, daemon=True)
        t.start()

    # 尝试连接老虎证券 API
    logger.info("尝试连接老虎证券 API...")
    tiger_connected = tiger_client.connect()
    if tiger_connected:
        tiger_status = tiger_client.get_status()
        logger.info(f"老虎API 连接成功! 模拟账号: {tiger_status['simulation_account']}")
    else:
        logger.info("老虎API 未配置，使用模拟模式 (yfinance)")

    # 从数据库恢复组合状态
    state_loaded = portfolio.load_state()
    if state_loaded:
        logger.info("✅ 组合状态已从数据库恢复")
    else:
        logger.info("🆕 无历史状态，使用默认初始资金")

    # 注册执行回调 - 每次交易后保存状态
    executor.on_order_filled(lambda trade: portfolio.save_state())

    # 启动实时引擎
    realtime_task = asyncio.create_task(realtime.start())

    # 注册实时更新回调
    realtime.on_tick(handle_market_tick)
    strategy_engine.on_analysis(handle_analysis_result)

    logger.info("Quant AI Trader 启动完成！")
    logger.info(f"模型状态: Transformer={'就绪' if trans_ready else '未训练'}, RL={'就绪' if rl_ready else '未训练'}")
    logger.info(f"美股: {len(data_config.US_TICKERS)} 只, 港股: {len(data_config.HK_TICKERS)} 只")
    logger.info(f"Web UI: http://localhost:{api_config.PORT}")
    logger.info(f"API:    http://localhost:{api_config.PORT}/docs")

    yield

    # 关闭
    realtime.stop()
    realtime_task.cancel()
    logger.info("Quant AI Trader 已关闭")


# ================================================================
# FastAPI 应用
# ================================================================

app = FastAPI(
    title="Quant AI Trader",
    description="最前沿科技打造的量化AI美股交易系统",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=api_config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(routes_data.router)
app.include_router(routes_trade.router)
app.include_router(routes_analysis.router)
app.include_router(routes_models.router)


# ================================================================
# WebSocket
# ================================================================

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """WebSocket 实时数据推送"""
    await ws.accept()
    active_connections.add(ws)
    logger.info(f"WebSocket 客户端连接 (当前: {len(active_connections)})")

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)

            if msg.get("type") == "subscribe":
                await ws.send_json({"type": "subscribed", "channels": msg.get("channels", [])})

            elif msg.get("type") == "analyze_now":
                tickers = msg.get("tickers", data_config.ALL_TICKERS)
                data_dict = await build_data_dict(tickers)
                prices = realtime.get_current_prices()
                results = strategy_engine.analyze_and_trade(tickers, data_dict, prices)
                await ws.send_json({"type": "analysis_result", "data": results})

    except WebSocketDisconnect:
        active_connections.discard(ws)
        logger.info(f"WebSocket 客户端断开 (当前: {len(active_connections)})")
    except Exception as e:
        logger.error(f"WebSocket 错误: {e}")
        active_connections.discard(ws)


# ================================================================
# 回调处理
# ================================================================

async def handle_market_tick(ticks: List[Dict]):
    """处理市场 tick 更新，支持多市场"""
    if not active_connections:
        return

    prices = {}
    for t in ticks:
        key = t.get("display", t["ticker"])
        prices[key] = t["price"]
    portfolio.update_value(prices)
    risk_manager.update_portfolio_state(
        portfolio.total_value, portfolio.cash,
        portfolio.positions, prices
    )

    message = json.dumps({
        "type": "market_tick",
        "data": {
            "ticks": ticks,
            "portfolio": portfolio.get_metrics(),
            "timestamp": datetime.now().isoformat(),
        }
    })
    await broadcast(message)


async def handle_analysis_result(results: Dict):
    """处理分析结果"""
    if not active_connections:
        return
    message = json.dumps({"type": "analysis_result", "data": results})
    await broadcast(message)


async def broadcast(message: str):
    """广播消息到所有WebSocket客户端"""
    if not active_connections:
        return
    dead_connections = set()
    for ws in active_connections:
        try:
            await ws.send_text(message)
        except Exception:
            dead_connections.add(ws)
    for ws in dead_connections:
        active_connections.discard(ws)


async def build_data_dict(tickers: List[str]) -> Dict:
    """构建模型输入数据"""
    data_dict = {}
    for ticker in tickers:
        df = market_data.get_historical_data(ticker, period="3mo", interval="1d")
        if df.empty:
            continue
        df = data_pipeline.process(df)
        features = df[[c for c in data_pipeline.FEATURE_COLUMNS if c in df.columns]].values
        data_dict[ticker] = {"features": features}
    return data_dict


# ================================================================
# 健康检查 & 首页
# ================================================================

@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "models": {
            "transformer": transformer.is_ready(),
            "rl_agent": rl_agent.is_ready(),
        },
        "portfolio_value": portfolio.total_value,
        "ws_connections": len(active_connections),
    }


@app.get("/")
async def root():
    """返回系统信息"""
    return {
        "name": "Quant AI Trader",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "frontend": "http://localhost:5173",
    }
