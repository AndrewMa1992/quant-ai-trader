"""services/factor_service/api/routes.py – REST API routes for the factor service.

Endpoints:
- GET /factors – List all registered factors
- GET /factors/{name} – Get factor details
- GET /ic-analysis – Rank IC analysis
- GET /correlation – Factor correlation matrix
- GET /decay – Factor IC decay analysis
- POST /compute – Compute specified factors for given data
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field

from configs.factor_registry import FACTOR_REGISTRY, get_all_factor_ids, get_factor_by_id
from services.factor_service.config import factor_config
from services.factor_service.engine.factor_engine import FactorEngine
from services.factor_service.evaluation.decay import DecayAnalyzer
from services.factor_service.evaluation.stratification import StratificationAnalyzer
from services.factor_service.evaluation.fama_macbeth import FamaMacBeth
from shared.core.exceptions import FactorComputationError, FactorNotFoundError
from shared.core.logger import get_logger
from shared.schema import APIResponse

router = APIRouter()


class ComputeRequest(BaseModel):
    """Request body for factor computation."""
    tickers: list[str] = Field(default_factory=list, description="Tickers to compute factors for")
    factor_names: list[str] = Field(default_factory=list, description="Factor IDs to compute (empty = all)")
    start_date: str | None = Field(default=None, description="Start date (YYYY-MM-DD)")
    end_date: str | None = Field(default=None, description="End date (YYYY-MM-DD)")


# Engine singleton
_engine: FactorEngine | None = None


def _get_engine() -> FactorEngine:
    global _engine
    if _engine is None:
        _engine = FactorEngine()
        _engine.register_all()
    return _engine


@router.get("/factors")
async def list_factors(
    category: str | None = Query(default=None, description="Filter by category"),
) -> APIResponse:
    """List all registered factors with optional category filter."""
    try:
        if category and category in FACTOR_REGISTRY:
            factors = FACTOR_REGISTRY[category]
        elif category:
            factors = []
        else:
            factors = []
            for cat_factors in FACTOR_REGISTRY.values():
                factors.extend(cat_factors)

        return APIResponse(
            success=True,
            message=f"Returned {len(factors)} factors",
            data={
                "count": len(factors),
                "categories": {c: len(f) for c, f in FACTOR_REGISTRY.items()},
                "factors": factors,
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/factors/{name}")
async def get_factor(name: str) -> APIResponse:
    """Get detailed information about a specific factor."""
    try:
        factor = get_factor_by_id(name)
        if factor is None:
            raise HTTPException(status_code=404, detail=f"Factor '{name}' not found")

        return APIResponse(
            success=True,
            message=f"Factor {name}",
            data=dict(factor),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ic-summary")
async def get_ic_summary(
    limit: int = Query(default=40, ge=1, le=113, description="Max factors to score"),
) -> APIResponse:
    """Rank factors by IC computed on stored daily bars."""
    log = get_logger(__name__)
    try:
        from services.factor_service.evaluation.live_panel import ic_summary, load_ohlcv

        names = list(load_ohlcv().keys())
        rows = ic_summary(limit=limit)
        return APIResponse(
            success=True,
            message=f"IC summary for {len(rows)} factors on {len(names)} stored names",
            data={"factors": rows, "tickers": names, "count": len(rows)},
        )
    except Exception as e:
        log.exception(f"IC summary failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ic-analysis")
async def get_ic_analysis(
    factor_name: str = Query(..., description="Factor ID"),
    window: int = Query(default=252, description="Rolling IC window"),
) -> APIResponse:
    """Rank IC for one factor, from stored daily bars."""
    log = get_logger(__name__)
    try:
        from services.factor_service.evaluation.live_panel import ic_series

        ic_result = ic_series(factor_name)
        ic_result["rolling_window"] = window
        return APIResponse(
            success=True,
            message=f"IC analysis for {factor_name}",
            data={
                "factor_name": factor_name,
                **ic_result,
            },
        )
    except Exception as e:
        log.exception(f"IC analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/correlation")
async def get_correlation(
    factor_names: str = Query(default="", description="Comma-separated factor IDs"),
) -> APIResponse:
    """Pairwise correlation of factors computed on stored bars."""
    log = get_logger(__name__)
    try:
        from services.factor_service.evaluation.correlation import FactorCorrelation
        from services.factor_service.evaluation.live_panel import correlation_matrix

        names = [n.strip() for n in factor_names.split(",") if n.strip()]
        if not names:
            names = get_all_factor_ids()[:12]

        panel, used = correlation_matrix(names)
        if panel.empty:
            return APIResponse(
                success=True,
                message="No stored bars for a correlation matrix",
                data={
                    "factors": [],
                    "correlation_matrix": {},
                    "redundant_pairs": [],
                    "threshold": factor_config.CORRELATION_THRESHOLD,
                },
            )

        corr = FactorCorrelation(threshold=factor_config.CORRELATION_THRESHOLD)
        matrix, redundant_pairs = corr.compute_correlation_matrix(panel)

        return APIResponse(
            success=True,
            message=f"Correlation matrix for {len(used)} factors",
            data={
                "factors": used,
                "correlation_matrix": matrix.to_dict(),
                "redundant_pairs": redundant_pairs,
                "threshold": factor_config.CORRELATION_THRESHOLD,
            },
        )
    except Exception as e:
        log.exception(f"Correlation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/decay")
async def get_decay(
    factor_name: str = Query(..., description="Factor ID"),
    max_lags: int = Query(default=20, description="Maximum lag periods"),
) -> APIResponse:
    """IC decay for one factor, from stored daily bars."""
    log = get_logger(__name__)
    try:
        from services.factor_service.evaluation.live_panel import mean_factor_and_returns

        decay = DecayAnalyzer(max_lags=max_lags)
        factor_values, returns = mean_factor_and_returns(factor_name)
        if factor_values.empty or returns.empty:
            return APIResponse(
                success=True,
                message=f"No stored bars for decay of {factor_name}",
                data={"factor_name": factor_name, "half_life": None, "decay_curve": []},
            )

        result = decay.analyze(factor_values.dropna(), returns.reindex(factor_values.index).fillna(0))

        return APIResponse(
            success=True,
            message=f"Decay analysis for {factor_name}",
            data={
                "factor_name": factor_name,
                **result,
            },
        )
    except Exception as e:
        log.exception(f"Decay analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/compute")
async def compute_factors(req: ComputeRequest) -> APIResponse:
    """Compute factors on stored daily bars for the requested tickers."""
    log = get_logger(__name__)
    try:
        from services.factor_service.evaluation.live_panel import load_ohlcv, resolve_factor_id

        engine = _get_engine()
        stored = load_ohlcv(max_names=24)
        requested = [t.strip().upper() for t in req.tickers if t.strip()] or list(stored.keys())
        dfs = {ticker: stored[ticker] for ticker in requested if ticker in stored}
        if not dfs:
            # Try the stored names as-is (HK tickers keep their suffix).
            for ticker in req.tickers:
                frame = stored.get(ticker) or stored.get(ticker.strip())
                if frame is not None:
                    dfs[ticker] = frame
        if not dfs:
            return APIResponse(
                success=True,
                message="No stored bars for the requested tickers",
                data={"tickers": [], "factor_count": 0, "available_factors": get_all_factor_ids()},
            )

        factor_ids = None
        if req.factor_names:
            factor_ids = [resolve_factor_id(name) or name for name in req.factor_names]

        results = engine.compute_all_multi(dfs, factor_ids)
        sample = next(iter(results.values())) if results else None
        factor_count = 0
        if sample is not None:
            base_cols = {"open", "high", "low", "close", "adj_close", "volume"}
            factor_count = len([c for c in sample.columns if str(c) not in base_cols])
        index = sample.index if sample is not None and len(sample.index) else []

        return APIResponse(
            success=True,
            message=f"Computed factors for {len(dfs)} stored tickers",
            data={
                "tickers": list(dfs.keys()),
                "factor_count": factor_count,
                "date_range": [str(index[0].date()), str(index[-1].date())] if len(index) else [],
                "available_factors": get_all_factor_ids(),
            },
        )
    except FactorComputationError as e:
        raise HTTPException(status_code=500, detail=e.to_dict())
    except Exception as e:
        log.exception(f"Factor computation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
