"""services/factor_service/engine/factor_engine.py – Factor computation engine.

Manages factor registration, batch computation, and post-processing:
- Vectorized batch factor computation
- Factor normalization (z-score cross-sectional)
- Outlier winsorization
- Sector neutralization
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger

from services.factor_service.config import factor_config
from services.factor_service.engine.factor_base import FactorBase
from shared.core.exceptions import FactorComputationError, FactorNotFoundError


class FactorEngine:
    """Central engine for factor registration and batch computation.

    Factors are registered via register() and computed in bulk via
    compute_all() which runs all factors in parallel on the input DataFrame.

    Attributes:
        factors: Dictionary mapping factor_id → FactorBase instance.
        _computed: Set of already-computed factor IDs (for dependency tracking).
    """

    def __init__(self) -> None:
        self.factors: dict[str, FactorBase] = {}
        self._computed: set[str] = set()

    def register(self, factor: FactorBase) -> None:
        """Register a factor instance with the engine.

        Args:
            factor: A FactorBase subclass instance.
        """
        self.factors[factor.factor_id] = factor
        logger.debug(f"Registered factor: {factor.factor_id} ({factor.name})")

    def register_all(self) -> None:
        """Auto-discover and register all factor implementations.

        Scans the factors subpackage and instantiates all FactorBase subclasses.
        """
        from services.factor_service.factors.technical import TECHNICAL_FACTORS
        from services.factor_service.factors.fundamental import FUNDAMENTAL_FACTORS
        from services.factor_service.factors.alternative import ALTERNATIVE_FACTORS
        from services.factor_service.factors.microstructure import MICROSTRUCTURE_FACTORS

        all_factors = (
            TECHNICAL_FACTORS
            + FUNDAMENTAL_FACTORS
            + ALTERNATIVE_FACTORS
            + MICROSTRUCTURE_FACTORS
        )

        for factor in all_factors:
            self.register(factor)

        logger.info(f"Registered {len(self.factors)} factors total")

    def get(self, factor_id: str) -> FactorBase:
        """Get a registered factor by ID.

        Args:
            factor_id: Factor identifier.

        Returns:
            FactorBase instance.

        Raises:
            FactorNotFoundError: If factor not registered.
        """
        if factor_id not in self.factors:
            raise FactorNotFoundError(
                f"Factor '{factor_id}' not registered",
                details={"available": list(self.factors.keys())[:20]},
            )
        return self.factors[factor_id]

    def compute(
        self,
        df: pd.DataFrame,
        factor_id: str,
    ) -> pd.Series:
        """Compute a single factor.

        Args:
            df: OHLCV DataFrame (plus prior factors).
            factor_id: Factor ID to compute.

        Returns:
            Series of factor values indexed by date.
        """
        factor = self.get(factor_id)
        try:
            result = factor.compute(df)
            if not isinstance(result, pd.Series):
                result = pd.Series(result, index=df.index)
            self._computed.add(factor_id)
            return result
        except Exception as e:
            raise FactorComputationError(
                f"Factor '{factor_id}' computation failed: {e}",
                details={"factor_id": factor_id, "error": str(e)},
            )

    def compute_all(
        self,
        df: pd.DataFrame,
        factor_ids: list[str] | None = None,
    ) -> pd.DataFrame:
        """Compute multiple factors on the same DataFrame.

        Factors are computed sequentially (some depend on prior factors)
        and results are merged into the output.

        Args:
            df: OHLCV DataFrame indexed by date.
            factor_ids: Optional list of factor IDs (None = all registered).

        Returns:
            DataFrame with factor columns added.
        """
        ids = factor_ids or list(self.factors.keys())
        result_df = df.copy()
        self._computed = set()

        for fid in ids:
            try:
                series = self.compute(result_df, fid)
                if series is not None and not series.empty:
                    result_df[fid] = series
            except FactorComputationError as e:
                logger.warning(f"Skipping factor {fid}: {e}")
                continue
            except Exception as e:
                logger.error(f"Unexpected error computing {fid}: {e}")
                continue

        return result_df

    def compute_all_multi(
        self,
        dfs: dict[str, pd.DataFrame],
        factor_ids: list[str] | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Compute factors across multiple tickers.

        Args:
            dfs: Dict of ticker → DataFrame.
            factor_ids: Factor IDs to compute.

        Returns:
            Dict of ticker → DataFrame with factors.
        """
        results: dict[str, pd.DataFrame] = {}
        for ticker, df in dfs.items():
            try:
                results[ticker] = self.compute_all(df, factor_ids)
            except Exception as e:
                # P0 fix: Downgrade to WARNING — ticker-level failure is non-fatal.
                logger.warning(f"Factor computation failed for {ticker}: {e}")
                results[ticker] = df
        return results

    def winsorize(
        self,
        series: pd.Series,
        pct: float | None = None,
    ) -> pd.Series:
        """Winsorize outliers at both tails.

        Args:
            series: Factor values.
            pct: Percentile to clip (e.g. 0.01 clips at 1st and 99th).

        Returns:
            Winsorized series.
        """
        pct = pct or factor_config.OUTLIER_WINSORIZE_PCT
        lower = series.quantile(pct)
        upper = series.quantile(1.0 - pct)
        return series.clip(lower=lower, upper=upper)

    def normalize_cross_sectional(
        self,
        series: pd.Series,
    ) -> pd.Series:
        """Cross-sectional z-score normalization.

        Args:
            series: Raw factor values.

        Returns:
            Z-scored factor values.
        """
        mean = series.mean()
        std = max(series.std(), 1e-8)
        return (series - mean) / std

    def neutralize_sector(
        self,
        factor_series: pd.Series,
        sectors: pd.Series,
    ) -> pd.Series:
        """Sector-neutralize a factor by subtracting sector means.

        Args:
            factor_series: Factor values indexed by ticker.
            sectors: Sector labels indexed by ticker.

        Returns:
            Sector-neutralized factor series.
        """
        if not factor_config.NEUTRALIZE_SECTORS:
            return factor_series

        result = factor_series.copy()
        for sector in sectors.unique():
            mask = sectors == sector
            if mask.sum() > 1:
                result[mask] = result[mask] - result[mask].mean()
        return result

    def post_process(
        self,
        factor_series: pd.Series,
        sectors: pd.Series | None = None,
    ) -> pd.Series:
        """Apply standard post-processing pipeline.

        Steps:
        1. Winsorize outliers
        2. Cross-sectional z-score
        3. Sector neutralize (optional)

        Args:
            factor_series: Raw factor values.
            sectors: Optional sector labels for neutralization.

        Returns:
            Processed factor series.
        """
        result = self.winsorize(factor_series)
        result = self.normalize_cross_sectional(result)
        if sectors is not None:
            result = self.neutralize_sector(result, sectors)
        return result
