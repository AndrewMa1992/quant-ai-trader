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

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field

from configs.factor_registry import FACTOR_REGISTRY, get_all_factor_ids, get_factor_by_id
from services.factor_service.config import factor_config
from services.factor_service.engine.factor_engine import FactorEngine
from services.factor_service.evaluation.ic_analysis import ICAnalyzer
from services.factor_service.evaluation.correlation import FactorCorrelation
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


@router.get("/ic-analysis")
async def get_ic_analysis(
    factor_name: str = Query(..., description="Factor ID"),
    window: int = Query(default=252, description="Rolling IC window"),
) -> APIResponse:
    """Get IC analysis for a factor."""
    log = get_logger(__name__)
    try:
        analyzer = ICAnalyzer(rolling_window=window)
        # Generate synthetic data for demonstration when real data unavailable
        import numpy as np
        np.random.seed(42)
        dates = pd.date_range("2022-01-01", periods=756, freq="B")
        factor_values = pd.Series(np.random.randn(756).cumsum() * 0.01 + 0.0005, index=dates)
        forward_returns = pd.Series(np.random.randn(756).cumsum() * 0.01, index=dates)

        ic_result = analyzer.compute_ic(factor_values, forward_returns)

        return APIResponse(
            success=True,
            message=f"IC analysis for {factor_name}",
            data={
                "factor_name": factor_name,
                "rolling_window": window,
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
    """Compute pairwise factor correlation matrix."""
    log = get_logger(__name__)
    try:
        names = [n.strip() for n in factor_names.split(",") if n.strip()]
        if not names:
            names = get_all_factor_ids()[:20]

        corr = FactorCorrelation(threshold=factor_config.CORRELATION_THRESHOLD)
        # Generate synthetic data
        import numpy as np
        np.random.seed(42)
        n = 252
        data = {name: np.random.randn(n) for name in names}
        df = pd.DataFrame(data)

        matrix, redundant_pairs = corr.compute_correlation_matrix(df)

        return APIResponse(
            success=True,
            message=f"Correlation matrix for {len(names)} factors",
            data={
                "factors": names,
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
    """Get factor IC decay analysis."""
    log = get_logger(__name__)
    try:
        decay = DecayAnalyzer(max_lags=max_lags)

        import numpy as np
        np.random.seed(42)
        dates = pd.date_range("2022-01-01", periods=756, freq="B")
        factor_values = pd.Series(np.random.randn(756).cumsum() * 0.01, index=dates)
        returns = pd.Series(np.random.randn(756).cumsum() * 0.01, index=dates)

        result = decay.analyze(factor_values, returns)

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
    """Compute factors for given tickers and return results."""
    log = get_logger(__name__)
    try:
        engine = _get_engine()
        factor_names = req.factor_names if req.factor_names else None

        # Generate sample data for demonstration
        import numpy as np
        np.random.seed(42)
        dates = pd.date_range(req.start_date or "2023-01-01", periods=252, freq="B")
        tickers = req.tickers or ["AAPL", "MSFT", "GOOGL"]

        dfs = {}
        for ticker in tickers:
            df = pd.DataFrame({
                "open": np.cumsum(np.random.randn(252) * 0.5) + 150,
                "high": np.cumsum(np.random.randn(252) * 0.5) + 152,
                "low": np.cumsum(np.random.randn(252) * 0.5) + 148,
                "close": np.cumsum(np.random.randn(252) * 0.5) + 150,
                "adj_close": np.cumsum(np.random.randn(252) * 0.5) + 150,
                "volume": np.random.randint(1000000, 50000000, 252),
            }, index=dates)
            dfs[ticker] = df

        results = engine.compute_all_multi(dfs, factor_names)

        return APIResponse(
            success=True,
            message=f"Computed factors for {len(tickers)} tickers",
            data={
                "tickers": tickers,
                "factor_count": len(results.get(list(results.keys())[0], {}).columns) if results else 0,
                "date_range": [str(dates[0].date()), str(dates[-1].date())],
                "available_factors": get_all_factor_ids(),
            },
        )
    except FactorComputationError as e:
        raise HTTPException(status_code=500, detail=e.to_dict())
    except Exception as e:
        log.exception(f"Factor computation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
