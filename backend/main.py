"""
Quant AI Trader - FastAPI 涓诲叆鍙?WebSocket 瀹炴椂鎺ㄩ€?+ REST API + 瀹氭椂浠诲姟
"""
import asyncio
import json
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Dict, List, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from backend.config import api_config, data_config
from backend.data_engine import MarketDataEngine, DataPipeline
from backend.services.signal_history import SignalHistory
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
from backend.data_engine.tiger_client import tiger_client
from backend.api import (
    routes_data, routes_trade, routes_analysis, routes_models
)


# ================================================================
# 鍏ㄥ眬缁勪欢
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

# WebSocket 杩炴帴绠＄悊
active_connections: Set[WebSocket] = set()


# ================================================================
# 鐢熷懡鍛ㄦ湡
# ================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """搴旂敤鐢熷懡鍛ㄦ湡绠＄悊"""
    logger.info("Quant AI Trader 鍚姩涓?..")

    # 鍒濆鍖栦俊鍙峰巻鍙插瓨鍌?    signal_history_store = SignalHistory()
    routes_analysis.init_signal_history(signal_history_store)

    # 鍒濆鍖栬矾鐢?    routes_trade.init(executor, portfolio, risk_manager, store)
    routes_analysis.init(strategy_engine, ensemble, backtester)
    routes_models.init(trainer)

    # 灏濊瘯鍔犺浇妯″瀷锛堜娇鐢?trainer 鍋氱粺涓€鍔犺浇锛?    trans_ready, rl_ready = trainer.load_or_retrain()
    logger.info(f"妯″瀷鍔犺浇: Transformer={'灏辩华' if trans_ready else '鏈缁?}, RL={'灏辩华' if rl_ready else '鏈缁?}")
    if not trans_ready or not rl_ready:
        logger.info("妯″瀷鏈缁冿紝鍚庡彴鍚姩璁粌...")
        import threading
        t = threading.Thread(target=trainer.train_all, daemon=True)
        t.start()

    # 灏濊瘯杩炴帴鑰佽檸璇佸埜 API
    logger.info("灏濊瘯杩炴帴鑰佽檸璇佸埜 API...")
    tiger_connected = tiger_client.connect()
    if tiger_connected:
        tiger_status = tiger_client.get_status()
        logger.info(f"鑰佽檸API 杩炴帴鎴愬姛! 妯℃嫙璐﹀彿: {tiger_status['simulation_account']}")
    else:
        logger.info("鑰佽檸API 鏈厤缃紝浣跨敤妯℃嫙妯″紡 (yfinance)")

    # 浠庢暟鎹簱鎭㈠缁勫悎鐘舵€?    state_loaded = portfolio.load_state()
    if state_loaded:
        logger.info("鉁?缁勫悎鐘舵€佸凡浠庢暟鎹簱鎭㈠")
    else:
        logger.info("馃啎 鏃犲巻鍙茬姸鎬侊紝浣跨敤榛樿鍒濆璧勯噾")

    # 娉ㄥ唽鎵ц鍥炶皟 - 姣忔浜ゆ槗鍚庝繚瀛樼姸鎬?    executor.on_order_filled(lambda trade: portfolio.save_state())

    # 鍚姩瀹炴椂寮曟搸
    realtime_task = asyncio.create_task(realtime.start())

    # 娉ㄥ唽瀹炴椂鏇存柊鍥炶皟
    realtime.on_tick(handle_market_tick)
    strategy_engine.on_analysis(handle_analysis_result)

    logger.info("Quant AI Trader 鍚姩瀹屾垚锛?)
    logger.info(f"妯″瀷鐘舵€? Transformer={'灏辩华' if trans_ready else '鏈缁?}, RL={'灏辩华' if rl_ready else '鏈缁?}")
    logger.info(f"缇庤偂: {len(data_config.US_TICKERS)} 鍙? 娓偂: {len(data_config.HK_TICKERS)} 鍙?)
    logger.info(f"Web UI: http://localhost:{api_config.PORT}")
    logger.info(f"API:    http://localhost:{api_config.PORT}/docs")

    yield

    # 鍏抽棴
    realtime.stop()
    realtime_task.cancel()
    logger.info("Quant AI Trader 宸插叧闂?)


# ================================================================
# FastAPI 搴旂敤
# ================================================================

app = FastAPI(
    title="Quant AI Trader",
    description="鏈€鍓嶆部绉戞妧鎵撻€犵殑閲忓寲AI缇庤偂浜ゆ槗绯荤粺",
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

# 娉ㄥ唽璺敱
app.include_router(routes_data.router)
app.include_router(routes_trade.router)
app.include_router(routes_analysis.router)
app.include_router(routes_models.router)


# ================================================================
# WebSocket
# ================================================================

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """WebSocket 瀹炴椂鏁版嵁鎺ㄩ€?""
    await ws.accept()
    active_connections.add(ws)
    logger.info(f"WebSocket 瀹㈡埛绔繛鎺?(褰撳墠: {len(active_connections)})")

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
        logger.info(f"WebSocket 瀹㈡埛绔柇寮€ (褰撳墠: {len(active_connections)})")
    except Exception as e:
        logger.error(f"WebSocket 閿欒: {e}")
        active_connections.discard(ws)


# ================================================================
# 鍥炶皟澶勭悊
# ================================================================

async def handle_market_tick(ticks: List[Dict]):
    """澶勭悊甯傚満 tick 鏇存柊锛屾敮鎸佸甯傚満"""
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
    """澶勭悊鍒嗘瀽缁撴灉"""
    if not active_connections:
        return
    message = json.dumps({"type": "analysis_result", "data": results})
    await broadcast(message)


async def broadcast(message: str):
    """骞挎挱娑堟伅鍒版墍鏈塛ebSocket瀹㈡埛绔?""
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
    """鏋勫缓妯″瀷杈撳叆鏁版嵁"""
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
# 鍋ュ悍妫€鏌?& 棣栭〉
# ================================================================

@app.get("/health")
async def health():
    """鍋ュ悍妫€鏌?""
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
    """杩斿洖绯荤粺淇℃伅"""
    return {
        "name": "Quant AI Trader",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "frontend": "http://localhost:5180",
    }

