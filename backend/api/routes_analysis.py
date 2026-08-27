"""
Analysis API routes — live trading signals.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query

from configs.settings import settings
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
    """Return the latest signals."""
    if strategy is None:
        return {"error": "Strategy is not initialized"}
    return {
        "signals": {
            ticker: signal
            for ticker, signal in strategy.last_signals.items()
        },
        "cycle": strategy._total_cycles,
    }


@router.get("/ensemble-status")
async def get_ensemble_status():
    """Return ensemble engine status."""
    if ensemble is None:
        return {"error": "Ensemble engine is not initialized"}
    return ensemble.get_status()


@router.get("/strategy-status")
async def get_strategy_status():
    """Return strategy status."""
    if strategy is None:
        return {"error": "Strategy is not initialized"}
    return strategy.get_status()


@router.get("/backtest-results")
async def get_backtest_results():
    """Return backtest results."""
    if backtester is None:
        return {"error": "Backtester is not initialized"}
    return {
        name: {k: v for k, v in result.items() if k != "value_history"}
        for name, result in backtester.results.items()
    }


@router.post("/run-backtest")
async def run_backtest():
    """Run a backtest."""
    return {"message": "Backtest queued", "status": "pending"}


@router.post("/run-analysis")
async def run_analysis(req: RunAnalysisRequest = None):
    """Run one analysis cycle and return signal cards."""
    global strategy, signal_history
    if strategy is None:
        return {"status": "error", "message": "Strategy is not initialized"}

    from backend.data_engine import MarketDataEngine, DataPipeline

    # Determine tickers to analyze
    tickers = req.tickers if req and req.tickers else settings.DATA_ALL_TICKERS

    # Fetch market data
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
                # Latest price (compatible with mixed-case column names)
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
            "status": "error", "message": "Unable to fetch market data",
            "signals": {}, "total": 0,
        }

    # Run analysis
    try:
        strategy.analyze_and_trade(tickers, data_dict, prices)
    except Exception as e:
        return {
            "status": "error", "message": f"Analysis failed: {str(e)}",
            "signals": {}, "total": 0,
        }

    # Build signal cards and persist history
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
    """Return signal history."""
    if signal_history is None:
        return {"status": "error", "message": "Signal history is not initialized"}
    if ticker:
        return {"ticker": ticker, "history": signal_history.get_history(ticker)}
    return signal_history.get_all_history()
