"""
Quant AI Trader - FastAPI main entry (WebSocket + REST API + Frontend SPA)
"""
import asyncio
import json
from datetime import datetime
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, List, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from loguru import logger

from configs.settings import settings
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
from backend.data_engine.china_adapter import china_data_adapter
from backend.api import (
    routes_data, routes_trade, routes_analysis, routes_models
)
from backend.api.routes_factors import router as factors_router
from backend.api.routes_portfolio_history import router as portfolio_history_router
from backend.api.routes_portfolio_history import init as portfolio_history_init


# ================================================================
# Global Components
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
trainer = ModelTrainer(transformer=transformer, rl_agent=rl_agent)

realtime = RealtimeEngine(market_data, data_pipeline)

active_connections: Set[WebSocket] = set()

# 数据源状态缓存（启动时探测，/health 端点读取）
_data_source_status: Dict = {"primary": "unknown", "eastmoney": False, "efinance": False, "tencent": False, "yfinance": False}
_data_source_checked_at: str = ""


# ================================================================
# Lifespan
# ================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management"""
    logger.info("Quant AI Trader starting...")

    # Init signal history
    signal_history_store = SignalHistory()
    routes_analysis.init_signal_history(signal_history_store)

    # Init routes
    routes_trade.init(executor, portfolio, risk_manager, store)
    routes_analysis.init(strategy_engine, ensemble, backtester)
    routes_models.init(trainer)
    portfolio_history_init(store)

    # Load models via trainer (优雅降级：缺少依赖不崩溃)
    trans_ready, rl_ready = False, False
    try:
        trans_ready, rl_ready = trainer.load_or_retrain()
        logger.info(f"Model load: Transformer={'ready' if trans_ready else 'not trained'}, RL={'ready' if rl_ready else 'not trained'}")
    except Exception as e:
        logger.warning(f"⚠️ 模型加载失败 (非关键): {e}")
        logger.info("Model load: skipped (依赖缺失，非关键)")
    # ★ 禁用自动训练：训练应手动执行 python -c "ModelTrainer().train_all()"
    # 避免阻塞 API 响应和消耗资源

    # Connect Tiger API (优雅降级)
    tiger_connected = False
    try:
        logger.info("Connecting to Tiger API...")
        tiger_connected = tiger_client.connect()
        if tiger_connected:
            tiger_status = tiger_client.get_status()
            logger.info(f"Tiger API 已连接! 实盘账号: {tiger_status['real_account']}")
        else:
            logger.warning("⚠️ Tiger API 未连接，将无法获取实盘数据")
    except Exception as e:
        logger.warning(f"⚠️ Tiger API 连接异常 (非关键): {e}")

    # Restore portfolio state (local fallback)
    state_loaded = portfolio.load_state()
    if state_loaded:
        logger.info("Portfolio state restored from database (local)")
    else:
        logger.info("No history, using default initial capital")

    # ★ 关键：Tiger 连接成功后，同步真实持仓覆盖本地
    if tiger_connected:
        logger.info("🔄 从老虎证券同步真实持仓...")
        portfolio._tiger_initial_capital_synced = False  # ★ 强制重置，确保 initial_capital 从 Tiger 获取
        sync_result = portfolio.sync_from_tiger(force=True)
        if sync_result["synced"]:
            logger.info(
                f"✅ Tiger 同步成功: {sync_result['positions']} 只持仓, "
                f"现金 ${sync_result['cash']:,.2f}, 总资产 ${sync_result['total_value']:,.2f}"
            )
        else:
            logger.warning(f"⚠️ Tiger 同步未完成: {sync_result['source']}")

    # ★ 启动时探测各数据源可达性
    try:
        source_status = china_data_adapter.health_check()
        available_sources = [k for k, v in source_status.items() if v and k != "primary"]
        logger.info(f"数据源健康检查: primary={source_status.get('primary', 'unknown')}, 可用源: {available_sources}")
        # 缓存到全局变量供 /health 端点读取
        global _data_source_status, _data_source_checked_at
        _data_source_status = dict(source_status)
        _data_source_checked_at = datetime.now().isoformat()
    except Exception as e:
        logger.debug(f"数据源健康检查跳过: {e}")

    # Save state after each trade
    executor.on_order_filled(lambda trade: portfolio.save_state())

    # Start realtime engine
    realtime_task = asyncio.create_task(realtime.start())

    # Register callbacks
    realtime.on_tick(handle_market_tick)
    strategy_engine.on_analysis(handle_analysis_result)

    logger.info("Quant AI Trader started")
    logger.info(f"Model status: Transformer={'ready' if trans_ready else 'not trained'}, RL={'ready' if rl_ready else 'not trained'}")
    logger.info(f"US: {len(settings.data_us_tickers_list)} stocks, HK: {len(settings.data_hk_tickers_list)} stocks")
    logger.info(f"Web UI: http://localhost:{settings.API_PORT}")
    logger.info(f"API:    http://localhost:{settings.API_PORT}/docs")

    yield

    # Shutdown
    realtime.stop()
    realtime_task.cancel()
    logger.info("Quant AI Trader shutting down")


# ================================================================
# FastAPI App
# ================================================================

app = FastAPI(
    title="Quant AI Trader",
    description="Quantitative AI Stock Trading System",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routes
app.include_router(routes_data.router)
app.include_router(routes_trade.router)
app.include_router(routes_trade.risk_v2_router)
app.include_router(routes_analysis.router)
app.include_router(routes_models.router)
app.include_router(factors_router, prefix="/api/v2/factors", tags=["factors"])
app.include_router(portfolio_history_router, prefix="/api/v2", tags=["analysis-v2"])

# Mount frontend static files (production build)
FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"
if FRONTEND_DIST.exists() and (FRONTEND_DIST / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="frontend_assets")


# ================================================================
# WebSocket
# ================================================================

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """WebSocket realtime data push"""
    await ws.accept()
    active_connections.add(ws)
    logger.info(f"WebSocket client connected (active: {len(active_connections)})")

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)

            if msg.get("type") == "subscribe":
                await ws.send_json({"type": "subscribed", "channels": msg.get("channels", [])})

            elif msg.get("type") == "analyze_now":
                tickers = msg.get("tickers", settings.DATA_ALL_TICKERS)
                data_dict = await build_data_dict(tickers)
                prices = realtime.get_current_prices()
                results = strategy_engine.analyze_and_trade(tickers, data_dict, prices)
                await ws.send_json({"type": "analysis_result", "data": results})

    except WebSocketDisconnect:
        active_connections.discard(ws)
        logger.info(f"WebSocket client disconnected (active: {len(active_connections)})")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        active_connections.discard(ws)


# ================================================================
# Callback Handlers
# ================================================================

async def handle_market_tick(ticks: List[Dict]):
    """Handle market tick updates"""
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
    """Handle analysis results"""
    if not active_connections:
        return
    message = json.dumps({"type": "analysis_result", "data": results})
    await broadcast(message)


async def broadcast(message: str):
    """Broadcast to all WebSocket clients"""
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
    """Build model input data"""
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
# 实时数据推送端点（auto_trader → WebSocket → 前端）
# ================================================================

@app.post("/api/push/cycle-data")
async def push_cycle_data(data: Dict):
    """
    接收 auto_trader 推送的周期数据，广播到所有 WebSocket 客户端
    同时自动持久化到数据库
    """
    try:
        # 广播实时市场数据
        if data.get("prices"):
            await broadcast(json.dumps({
                "type": "market_update",
                "data": {
                    "prices": data["prices"],
                    "signals": data.get("signals", {}),
                    "trades": data.get("trades", []),
                    "portfolio": data.get("portfolio", {}),
                    "timestamp": datetime.now().isoformat(),
                }
            }))

        # 自动持久化
        store.save_price_ticks_batch(data.get("prices", {}))
        if data.get("signals"):
            store.save_signals_batch(data["signals"])
        if data.get("trades"):
            store.save_trades_batch(data["trades"])
        if data.get("portfolio"):
            store.save_snapshot({
                "timestamp": datetime.now().isoformat(),
                "total_value": data["portfolio"].get("total_value", 0),
                "cash": data["portfolio"].get("cash", 0),
                "positions_value": data["portfolio"].get("total_value", 0) - data["portfolio"].get("cash", 0),
                "total_pnl": data["portfolio"].get("total_pnl", 0),
            })

        return {"status": "ok", "connections": len(active_connections)}

    except Exception as e:
        logger.error(f"Push error: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/push/tiger-snapshot")
async def push_tiger_snapshot(data: Dict):
    """接收 Tiger 实时快照，广播到所有 WebSocket 前端"""
    try:
        await broadcast(json.dumps({
            "type": "tiger_snapshot",
            "data": {
                "portfolio_value": data.get("portfolio_value", 0),
                "cash": data.get("cash", 0),
                "positions": data.get("positions", {}),
                "pnl": data.get("pnl", 0),
                "pnl_pct": data.get("pnl_pct", 0),
                "timestamp": datetime.now().isoformat(),
            }
        }))
        return {"status": "ok", "connections": len(active_connections)}
    except Exception as e:
        logger.error(f"Tiger push error: {e}")
        return {"status": "error", "message": str(e)}


# ================================================================
# Health Check & Routes
# ================================================================

@app.get("/health")
async def health():
    # Tiger API 状态 — 包在 try/except 内防止报错影响整体健康检查
    tiger_status: Dict = {"connected": False, "account": ""}
    try:
        status = tiger_client.get_status()
        tiger_status["connected"] = status.get("connected", False)
        tiger_status["account"] = status.get("real_account", "") or status.get("simulation_account", "")
    except Exception as e:
        logger.debug(f"Tiger get_status() 调用失败: {e}")

    # 数据源状态 — 使用启动时缓存的结果
    ds_status = dict(_data_source_status)
    # 如果缓存为空（启动时健康检查失败），补充降级状态
    if not ds_status or ds_status.get("primary", "unknown") == "unknown":
        ds_status.update({"primary": "pending", "yfinance": True, "note": "health_check_not_run"})

    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "models": {
            "transformer": transformer.is_ready(),
            "rl_agent": rl_agent.is_ready(),
        },
        "tiger_api": tiger_status,
        "data_sources": {
            "checked_at": _data_source_checked_at or datetime.now().isoformat(),
            "primary": ds_status.get("primary", "unknown"),
            "sources": {
                "eastmoney": ds_status.get("eastmoney", False),
                "efinance": ds_status.get("efinance", False),
                "tencent": ds_status.get("tencent", False),
                "yfinance": ds_status.get("yfinance", False),
            },
        },
        "portfolio_value": portfolio.total_value,
        "ws_connections": len(active_connections),
    }


@app.get("/")
async def root():
    """Frontend SPA entry"""
    index_path = FRONTEND_DIST / "index.html"
    if FRONTEND_DIST.exists() and index_path.exists():
        return FileResponse(index_path)
    return {
        "name": "Quant AI Trader",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    """SPA fallback for client-side routing"""
    if full_path.startswith(("api/", "docs", "openapi.json", "ws")):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    index_path = FRONTEND_DIST / "index.html"
    if FRONTEND_DIST.exists() and index_path.exists():
        return FileResponse(index_path)
    return JSONResponse({"detail": "Frontend not built"}, status_code=404)
