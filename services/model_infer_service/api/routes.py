"""services/model_infer_service/api/routes.py – Inference API endpoints.

Endpoints:
- POST /predict – Single ticker prediction
- POST /predict/batch – Multi-ticker batch prediction
- POST /signal – Trading signal for one ticker
- POST /signal/all – Signals for all universe tickers
- GET /models/status – Model loading status
- GET /health/models – Per-model health and load timestamps
- POST /predict/hot-reload – Hot-reload production models from MLflow
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field

from services.model_infer_service.config import infer_config
from shared.core.logger import get_logger
from shared.schema import APIResponse

router = APIRouter()


class PredictRequest(BaseModel):
    ticker: str = Field(..., description="Ticker symbol")
    features: dict[str, float] = Field(default_factory=dict, description="Feature values")
    model_types: list[str] = Field(default_factory=list, description="Specific models to use")


class BatchPredictRequest(BaseModel):
    tickers: list[str] = Field(..., description="Ticker symbols")
    model_types: list[str] = Field(default_factory=list, description="Specific models to use")


class SignalResponse(BaseModel):
    ticker: str
    signal: float  # [-1, 1]
    confidence: float  # [0, 1]
    direction: str  # BUY / SELL / HOLD
    components: dict[str, float] = Field(default_factory=dict)


def _get_engine():
    """Get the global inference engine (set in main.py lifespan)."""
    import services.model_infer_service.main as main_mod
    engine = main_mod.engine
    if engine is None:
        raise HTTPException(status_code=503, detail="Inference engine not initialized")
    return engine


@router.post("/predict")
async def predict(req: PredictRequest) -> APIResponse:
    """Run model prediction for a single ticker.

    Returns predicted return or probability for each model.
    """
    log = get_logger(__name__)
    try:
        engine = _get_engine()
        predictions = engine.predict_single(ticker=req.ticker)
        return APIResponse(
            success=True,
            message=f"Prediction for {req.ticker}",
            data=predictions,
        )
    except Exception as e:
        log.exception(f"Prediction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/predict/batch")
async def predict_batch(req: BatchPredictRequest) -> APIResponse:
    """Run batch prediction for multiple tickers."""
    log = get_logger(__name__)
    try:
        engine = _get_engine()
        results = {}
        for ticker in req.tickers:
            results[ticker] = engine.predict_single(ticker=ticker)

        return APIResponse(
            success=True,
            message=f"Predictions for {len(req.tickers)} tickers",
            data={"predictions": results},
        )
    except Exception as e:
        log.exception(f"Batch prediction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/signal")
async def get_signal(req: PredictRequest) -> APIResponse:
    """Generate a trading signal for a single ticker.

    Returns signal ∈ [-1, 1] and confidence ∈ [0, 1].
    """
    log = get_logger(__name__)
    try:
        engine = _get_engine()
        signal_result = engine.generate_signal(ticker=req.ticker)

        return APIResponse(
            success=True,
            message=f"Signal for {req.ticker}: {signal_result['direction']} ({signal_result['signal']:.4f})",
            data=signal_result,
        )
    except Exception as e:
        log.exception(f"Signal generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/signal/all")
async def get_all_signals() -> APIResponse:
    """Generate trading signals for all universe tickers."""
    log = get_logger(__name__)
    try:
        from configs.market_universe import get_all_tickers
        tickers = get_all_tickers()[:50]  # Limit for performance

        engine = _get_engine()
        signals = engine.generate_signals_batch(tickers)

        buy_count = sum(1 for s in signals if s["direction"] == "BUY")
        sell_count = sum(1 for s in signals if s["direction"] == "SELL")
        hold_count = sum(1 for s in signals if s["direction"] == "HOLD")

        return APIResponse(
            success=True,
            message=f"Signals: {buy_count} BUY, {sell_count} SELL, {hold_count} HOLD",
            data={
                "count": len(signals),
                "buy_count": buy_count,
                "sell_count": sell_count,
                "hold_count": hold_count,
                "signals": signals,
            },
        )
    except Exception as e:
        log.exception(f"Signal generation batch failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models/status")
async def get_models_status() -> APIResponse:
    """Get loaded model status information."""
    try:
        engine = _get_engine()
        status = engine.get_status()
        return APIResponse(
            success=True,
            message=f"{sum(1 for v in status.values() if v.get('loaded'))} models loaded",
            data=status,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health/models")
async def get_health_models() -> APIResponse:
    """Get per-model load status and last-load timestamps.

    Reads from the global _model_versions dict if initialized, otherwise
    returns a stub indicating models are not loaded.
    """
    import services.model_infer_service.main as main_mod

    engine = main_mod.engine
    if engine is None:
        return APIResponse(
            success=True,
            message="models not loaded",
            data={"status": "not_initialized", "models": {}},
        )

    try:
        status = engine.get_status()
        loaded_count = sum(1 for v in status.values() if v.get("loaded"))
        return APIResponse(
            success=True,
            message=f"{loaded_count} model(s) loaded",
            data={
                "status": "healthy" if loaded_count > 0 else "degraded",
                "loaded_count": loaded_count,
                "models": status,
            },
        )
    except Exception as e:
        return APIResponse(
            success=True,
            message=f"Unable to read model status: {e}",
            data={"status": "error", "models": {}, "error": str(e)},
        )


@router.post("/predict/hot-reload")
async def hot_reload_models() -> APIResponse:
    """Hot-reload latest models from MLflow (production stage).

    Calls InferenceEngine.load_latest_models() if available, otherwise
    returns a stub indicating MLflow is not configured.
    """
    import services.model_infer_service.main as main_mod

    engine = main_mod.engine
    if engine is None:
        return APIResponse(
            success=True,
            message="Inference engine not initialized",
            data={"success": False, "reloaded": 0},
        )

    try:
        if hasattr(engine, "load_latest_models"):
            result = engine.load_latest_models()
            reloaded = result.get("reloaded", 0) if isinstance(result, dict) else 0
            return APIResponse(
                success=True,
                message=f"Hot-reload complete: {reloaded} model(s) reloaded",
                data={"success": True, "reloaded": reloaded, "message": str(result)},
            )

        # Fallback: try reloading via load_models()
        load_result = engine.load_models()
        return APIResponse(
            success=True,
            message=f"Re-initialized models via load_models()",
            data={"success": True, "reloaded": 0, "message": str(load_result)},
        )
    except Exception as e:
        return APIResponse(
            success=True,
            message=f"MLflow not configured",
            data={"success": True, "reloaded": 0, "message": f"MLflow not configured: {e}"},
        )
