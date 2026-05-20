"""
分析接口路由 - 实时交易信号
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query

from backend.config import data_config
from backend.api.models.signal import (
    RunAnalysisRequest, RunAnalysisResponse,
    SignalCard,
)

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

strategy = None
ensemble = None
backtester = None
signal_history = None


def init(strat_ref, ensemble_ref, bt_ref):
    global strategy, ensemble, backtester
    strategy = strat_ref
    ensemble = ensemble_ref
    backtester = bt_ref


def init_signal_history(sh_ref):
    global signal_history
    signal_history = sh_ref


@router.get("/latest-signals")
async def get_latest_signals():
    """获取最新信号"""
    if strategy is None:
        return {"error": "策略未初始化"}
    return {
        "signals": {
            ticker: signal
            for ticker, signal in strategy.last_signals.items()
        },
        "cycle": strategy._total_cycles,
    }


@router.get("/ensemble-status")
async def get_ensemble_status():
    """获取融合引擎状态"""
    if ensemble is None:
        return {"error": "融合引擎未初始化"}
    return ensemble.get_status()


@router.get("/strategy-status")
async def get_strategy_status():
    """获取策略状态"""
    if strategy is None:
        return {"error": "策略未初始化"}
    return strategy.get_status()


@router.get("/backtest-results")
async def get_backtest_results():
    """获取回测结果"""
    if backtester is None:
        return {"error": "回测引擎未初始化"}
    return {
        name: {k: v for k, v in result.items() if k != "value_history"}
        for name, result in backtester.results.items()
    }


@router.post("/run-backtest")
async def run_backtest():
    """运行回测"""
    return {"message": "回测已排队", "status": "pending"}


@router.post("/run-analysis")
async def run_analysis(req: RunAnalysisRequest = None):
    """运行一次分析循环，返回信号卡片"""
    global strategy, signal_history
    if strategy is None:
        return {"status": "error", "message": "策略未初始化"}

    from backend.data_engine import MarketDataEngine, DataPipeline

    # 确定需要分析的 tickers
    tickers = req.tickers if req and req.tickers else data_config.ALL_TICKERS

    # 获取市场数据
    engine = MarketDataEngine()
    pipeline = DataPipeline()

    data_dict = {}
    prices = {}

    for ticker in tickers:
        try:
            df = engine.get_historical_data(ticker, period="3mo", interval="1d")
            if df is not None and not df.empty:
                processed = pipeline.process(df)
                if processed is not None:
                    features = processed.values if hasattr(processed, 'values') else processed
                    data_dict[ticker] = {"features": features}
                # 获取最新价格（兼容大小写列名）
                if 'Close' in df.columns:
                    price = float(df['Close'].iloc[-1])
                elif 'close' in df.columns:
                    price = float(df['close'].iloc[-1])
                else:
                    price = float(df.iloc[-1, df.columns.get_loc('close') if 'close' in df.columns else 0])
                prices[ticker] = price
        except Exception:
            continue

    if not data_dict:
        return {
            "status": "error", "message": "无法获取市场数据",
            "signals": {}, "total": 0,
        }

    # 执行分析
    try:
        strategy.analyze_and_trade(tickers, data_dict, prices)
    except Exception as e:
        return {
            "status": "error", "message": f"分析失败: {str(e)}",
            "signals": {}, "total": 0,
        }

    # 构建信号卡片并写入历史
    signal_cards = {}
    for ticker, signal in strategy.last_signals.items():
        card = SignalCard(
            ticker=ticker,
            decision=signal.get("decision", "hold"),
            strength=signal.get("strength", 0.0),
            confidence=signal.get("confidence", 0.0),
            position_size=signal.get("position_size", 0.0),
            ensemble_score=signal.get("ensemble_score", 0.0),
            details=signal.get("details", {}),
            timestamp=datetime.now().isoformat(),
        )
        signal_cards[ticker] = card.model_dump()
        if signal_history is not None:
            signal_history.append(ticker, signal)

    return RunAnalysisResponse(
        status="ok",
        total=len(signal_cards),
        timestamp=datetime.now().isoformat(),
        signals=signal_cards,
    ).model_dump()


@router.get("/signal-history")
async def get_signal_history(ticker: Optional[str] = Query(None)):
    """获取信号历史"""
    if signal_history is None:
        return {"status": "error", "message": "信号历史未初始化"}
    if ticker:
        return {"ticker": ticker, "history": signal_history.get_history(ticker)}
    return signal_history.get_all_history()
