"""services/model_infer_service/inference_engine.py – Central inference engine.

Orchestrates: load models → preprocess → multi-model inference → ensemble → signal.

Signal format per ticker:
- signal: float ∈ [-1, 1] (positive=buy, negative=sell, 0=hold)
- confidence: float ∈ [0, 1]
- direction: 'BUY' / 'SELL' / 'HOLD'

v2.3: predict_single / generate_signal now accept an optional ``features_row``
(Series) so callers can pass pre-computed factor data directly.  When the
ParquetStore has no data for a ticker (e.g. non-US markets), the pipeline
feeds factor data from Step 2 instead — avoiding the "0 signals" dead-end.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd
from loguru import logger

from services.data_service.storage.parquet_store import ParquetStore
from services.model_infer_service.config import infer_config
from services.model_infer_service.ensemble.bayesian_weighting import BayesianWeighting
from services.model_infer_service.ensemble.blender import SignalBlender
from services.model_infer_service.ensemble.market_state import MarketStateDetector
from services.model_infer_service.model_registry import ModelRegistry
from services.model_infer_service.models.gbdt_model import GBDTInference
from services.model_infer_service.models.transformer_model import TransformerInference
from services.model_infer_service.models.tcn_model import TCNInference
from services.model_infer_service.models.tft_model import TFTInference
from services.model_infer_service.models.rl_model import RLInference


class InferenceEngine:
    """Central inference engine coordinating model loading, prediction, and ensemble."""

    def __init__(self) -> None:
        self.registry = ModelRegistry()
        self.blender = SignalBlender()
        self.bayesian = BayesianWeighting()
        self.market_state = MarketStateDetector()

        self.models: dict[str, Any] = {
            "gbdt": GBDTInference(),
            "transformer": TransformerInference(),
            "tcn": TCNInference(),
            "tft": TFTInference(),
            "rl": RLInference(),
        }

        self._store = ParquetStore()

        # Initialize FactorEngine once and reuse across predictions.
        # Models were trained with 77 FactorEngine features; using the same
        # engine here ensures feature-shape consistency at inference time.
        self._factor_engine = None
        try:
            from services.factor_service.engine.factor_engine import FactorEngine

            self._factor_engine = FactorEngine()
            self._factor_engine.register_all()
            logger.info(
                f"InferenceEngine: FactorEngine ready with "
                f"{len(self._factor_engine.factors)} factors"
            )
        except Exception as e:
            logger.warning(f"InferenceEngine: FactorEngine not available: {e}")

        # Load training-time feature column order (77 columns).
        # Stored in feature_names.json — extracted from transformer checkpoint.
        self._feature_names: list[str] = self._load_feature_names()

    @staticmethod
    def _load_feature_names() -> list[str]:
        """Load the 77 training-time feature names in exact column order.

        Models were trained with: close, high, low, open, volume,
        ret_1d..ret_63d, F001..F311. The order is deterministic.
        """
        import json
        from pathlib import Path

        path = Path(__file__).parent.parent.parent / "data" / "models" / "feature_names.json"
        if path.exists():
            try:
                with open(path) as f:
                    names = json.load(f)
                if len(names) == 77:
                    return names
                logger.warning(f"feature_names.json has {len(names)} cols, expected 77")
            except Exception:
                pass

        # Fallback: reconstruct from FactorEngine + OHLCV + returns
        logger.warning("Reconstructing feature names from FactorEngine registry")
        names = ["close", "high", "low", "open", "volume",
                 "ret_1d", "ret_5d", "ret_21d", "ret_63d"]
        # FactorEngine uses F001–F311 naming
        from services.factor_service.engine.factor_engine import FactorEngine
        fe = FactorEngine()
        fe.register_all()
        for name in fe.factors:
            if name not in names:
                names.append(name)
        return names

    def load_models(self) -> dict[str, bool]:
        """Load all available production models.

        Returns:
            Dict of model_type → loaded status.
        """
        registry_info = self.registry.refresh()
        load_status: dict[str, bool] = {}

        for model_type, model in self.models.items():
            # Try MLflow first
            info = registry_info.get(model_type, {})
            model_uri = info.get("model_uri")

            # Also try local checkpoint
            local_path = self.registry.get_model_path(model_type)

            loaded = False
            if local_path:
                loaded = model.load(local_path)
                if loaded:
                    logger.info(f"Loaded {model_type} from local checkpoint")
                    load_status[model_type] = True
                    continue

            if model_uri:
                # For MLflow models, we'd use mlflow.pyfunc.load_model(model_uri)
                # For now, fall through to local
                loaded = model.load(local_path) if local_path else False

            load_status[model_type] = loaded

        return load_status

    def get_status(self) -> dict[str, dict[str, Any]]:
        """Get status of all models.

        Returns:
            Dict of model_type → {loaded, model_name}.
        """
        return {
            name: {
                "loaded": model.loaded,
                "model_name": model.model_name,
            }
            for name, model in self.models.items()
        }

    def _compute_basic_returns(self, df: pd.DataFrame) -> None:
        """Compute basic return features as a fallback when FactorEngine is unavailable.

        Mutates ``df`` in place by adding ``ret_1d``, ``ret_5d``, ``ret_21d``,
        and ``ret_63d`` columns.

        Args:
            df: OHLCV DataFrame (will be modified in place).
        """
        for p in [1, 5, 21, 63]:
            col = "adj_close" if "adj_close" in df.columns else "close"
            if col in df.columns:
                df[f"ret_{p}d"] = df[col].pct_change(p)

    def _build_features_from_parquet(self, ticker: str) -> Optional[pd.DataFrame]:
        """Build aligned 77-feature matrix from ParquetStore data.

        Reads OHLCV data, computes factors and returns, then aligns to the
        exact 77-column training feature order.

        Args:
            ticker: Stock ticker symbol.

        Returns:
            (N, 77) feature DataFrame, or None if data is insufficient.
        """
        df = self._store.read_daily(ticker)
        if df is None or len(df) < 60:
            logger.debug(
                f"Insufficient ParquetStore data for {ticker} "
                f"({len(df) if df is not None else 0} rows)"
            )
            return None

        df = df.tail(504).copy()

        # Compute factors
        if self._factor_engine is not None:
            try:
                df = self._factor_engine.compute_all(df)
            except Exception as e:
                logger.warning(f"FactorEngine failed for {ticker}, using basic features: {e}")
                self._compute_basic_returns(df)
        else:
            self._compute_basic_returns(df)

        self._compute_basic_returns(df)

        # Align to training column order
        return self._align_features(df, ticker)

    def _build_features_from_row(self, features_row: pd.Series) -> pd.DataFrame:
        """Build aligned 77-feature matrix from a single row of pre-computed factors.

        The row is broadcast to a 1-row DataFrame so models that need a
        sequence still work (they receive a length-1 sequence).

        Args:
            features_row: Series with factor values (ideally 77 columns matching
                          ``_feature_names``).

        Returns:
            (1, 77) feature DataFrame aligned to training column order.
        """
        # Build a DataFrame from the row
        row_df = pd.DataFrame([features_row])
        # Align to training column order
        return self._align_features(row_df, "row")

    def _align_features(self, df: pd.DataFrame, label: str) -> pd.DataFrame:
        """Align a DataFrame to the 77-feature training column order.

        Creates a DataFrame with exactly ``len(_feature_names)`` columns,
        copying values where column names match and filling 0.0 for missing
        columns.  Finally, reindexes to guarantee the output always has the
        exact column set.

        Args:
            df: Input DataFrame with factor/OHLCV columns.
            label: Ticker or identifier for debug logging.

        Returns:
            DataFrame with exactly ``_feature_names`` columns, NaN-filled and
            tail-truncated to the last 252 rows.
        """
        train_cols = self._feature_names

        aligned = pd.DataFrame(0.0, index=df.index, columns=train_cols)
        for col in train_cols:
            if col in df.columns:
                aligned[col] = df[col].values

        # Reindex to guarantee the exact column set (defense against edge cases)
        aligned = aligned.reindex(columns=train_cols, fill_value=0.0)

        missing = [c for c in train_cols if c not in df.columns]
        if missing:
            logger.debug(f"Missing features for {label} (padded=0): {missing[:5]}...")

        return aligned.fillna(0.0).tail(252)

    def predict_single(
        self,
        ticker: str,
        features_row: Optional[pd.Series] = None,
    ) -> dict[str, Any]:
        """Run all loaded models on a single ticker.

        Two data paths:
        1. **ParquetStore path** (default): reads OHLCV from ParquetStore,
           computes factors, aligns to 77 features.
        2. **Direct factor path**: when ``features_row`` is provided (from
           the pipeline's Step 2), uses pre-computed factors directly —
           skipping the ParquetStore read entirely.  This is essential for
           non-US tickers that have no ParquetStore data.

        Args:
            ticker: Stock ticker symbol.
            features_row: Optional Series of pre-computed factor values
                          (77 columns matching ``_feature_names``).

        Returns:
            Dict with per-model predictions.
        """
        # ── Choose data path ──────────────────────────────────────────
        if features_row is not None:
            X = self._build_features_from_row(features_row)
        else:
            X = self._build_features_from_parquet(ticker)
            if X is None:
                logger.warning(
                    f"Insufficient data for {ticker} "
                    f"(no ParquetStore data and no features_row provided)"
                )
                return {
                    "ticker": ticker,
                    "predictions": {},
                    "error": "Insufficient data",
                }

        predictions: dict[str, Any] = {}

        for model_type, model in self.models.items():
            if not model.loaded:
                continue
            try:
                raw_pred = model.predict(X)
                recent_pred = float(raw_pred[-1]) if len(raw_pred) > 0 else 0.0

                # Determine confidence
                if hasattr(model, "predict_direction_prob"):
                    probs = model.predict_direction_prob(X.tail(1))
                    confidence = max(float(probs["up_prob"][-1]), float(probs["down_prob"][-1]))
                else:
                    confidence = 0.5 + min(abs(recent_pred) * 2.0, 0.45)

                direction = "BUY" if recent_pred > 0.01 else ("SELL" if recent_pred < -0.01 else "HOLD")

                predictions[model_type] = {
                    "value": round(recent_pred, 6),
                    "confidence": round(confidence, 4),
                    "direction": direction,
                }

            except Exception as e:
                logger.error(f"Prediction failed for {model_type} on {ticker}: {e}")
                continue

        return {
            "ticker": ticker,
            "predictions": predictions,
            "available_models": len(predictions),
        }

    def generate_signal(
        self,
        ticker: str,
        features_row: Optional[pd.Series] = None,
    ) -> dict[str, Any]:
        """Generate a trading signal for a ticker.

        Orchestrates the full pipeline: load → predict → blend → signal.

        Args:
            ticker: Stock ticker.
            features_row: Optional pre-computed factor row (from pipeline
                          Step 2).  Bypasses ParquetStore when provided.

        Returns:
            Signal dict with signal, confidence, direction, components.
        """
        result = self.predict_single(ticker, features_row=features_row)
        predictions = result.get("predictions", {})

        if not predictions:
            return {
                "ticker": ticker,
                "signal": 0.0,
                "confidence": 0.0,
                "direction": "HOLD",
                "components": {},
            }

        # Get market-state-guided model subset
        available = list(predictions.keys())
        model_subset = self.market_state.get_model_subset(available)

        # Filter to subset
        subset_predictions = {
            k: v for k, v in predictions.items() if k in model_subset
        } if model_subset else predictions

        # Get Bayesian weights
        weights = self.bayesian.get_weights()
        if not weights:
            weights = {name: 1.0 / len(subset_predictions) for name in subset_predictions}

        # Blend
        blended = self.blender.blend(subset_predictions, weights)

        # When RL model is not loaded, other models' signals can be
        # overly conservative.  Apply a modest boost to the blended
        # signal to compensate for the missing RL contribution and
        # prevent all-zero signal cycles.
        rl_model_available = "rl" in predictions
        if not rl_model_available and len(subset_predictions) >= 2:
            boost_factor = 1.25
            blended["signal"] = round(
                float(np.clip(blended["signal"] * boost_factor,
                              -infer_config.SIGNAL_CLIP,
                              infer_config.SIGNAL_CLIP)),
                6,
            )
            # Re-derive direction with slightly looser thresholds
            sig = blended["signal"]
            if sig > 0.03:
                blended["direction"] = "BUY"
            elif sig < -0.03:
                blended["direction"] = "SELL"
            else:
                blended["direction"] = "HOLD"

        return {
            "ticker": ticker,
            "signal": blended["signal"],
            "confidence": blended["confidence"],
            "direction": blended["direction"],
            "components": blended.get("components", {}),
        }

    def generate_signals_batch(
        self,
        input_data: pd.DataFrame | list[str],
        top_n: int = 5,
        min_threshold: float = 0.03,
        min_confidence: float = 0.3,
    ) -> list[dict[str, Any]]:
        """Generate signals for multiple tickers, returning top-N by |signal|.

        Supports two input modes:
        1. pd.DataFrame with a 'ticker' column (from FactorEngine)
        2. list[str] of ticker symbols (direct lookup)

        All tickers are inferred, then filtered by min_threshold + min_confidence,
        sorted by |signal| descending, and the top_n are returned.

        Args:
            input_data: Factor DataFrame with 'ticker' column, or list of tickers.
            top_n: Maximum number of signals to return.
            min_threshold: Minimum absolute signal strength (floor).
            min_confidence: Minimum confidence score.

        Returns:
            List of signal dicts (top-N by |signal|), each with
            signal, confidence, direction, components.
        """
        if isinstance(input_data, pd.DataFrame):
            return self._generate_signals_from_factor_df(
                input_data, min_threshold, min_confidence, top_n,
            )
        return self._generate_signals_from_tickers(
            input_data, min_threshold, min_confidence, top_n,
        )

    def _get_factor_row_for_ticker(
        self,
        factor_df: pd.DataFrame,
        ticker: str,
    ) -> Optional[pd.Series]:
        """Extract a single factor row for a ticker from the factor DataFrame.

        Returns the last (most recent) row for the ticker, or None if not found.

        Args:
            factor_df: DataFrame from FactorEngine with 'ticker' column.
            ticker: Ticker to look up.

        Returns:
            Series of factor values, or None.
        """
        if "ticker" not in factor_df.columns:
            return None
        mask = factor_df["ticker"] == ticker
        rows = factor_df[mask]
        if rows.empty:
            return None
        # Take the last row (most recent data point)
        last_row = rows.iloc[-1]
        # Drop the 'ticker' column from features (it's not a model input)
        features = last_row.drop("ticker", errors="ignore")
        return features

    def _generate_signals_from_factor_df(
        self,
        factor_df: pd.DataFrame,
        min_threshold: float = 0.03,
        min_confidence: float = 0.3,
        top_n: int = 5,
    ) -> list[dict[str, Any]]:
        """Generate signals from FactorEngine-computed factor DataFrame.

        Full inference on all tickers, then Top-N selection by |signal| desc.
        For tickers with ParquetStore data, the engine loads full OHLCV history
        and recomputes factors for richer context.  For tickers WITHOUT
        ParquetStore data (e.g. non-US markets), the pre-computed factor row
        from ``factor_df`` is used directly — avoiding the "0 signals" dead-end
        for HK/SG/AU/NZ/CN markets.

        Args:
            factor_df: DataFrame from FactorEngine, must have 'ticker' column.
            min_threshold: Minimum absolute signal strength (floor).
            min_confidence: Minimum confidence score.
            top_n: Max signals to return.

        Returns:
            Top-N signal dicts sorted by |signal| descending.
        """
        all_signals: list[dict[str, Any]] = []
        tickers = (
            factor_df["ticker"].unique()
            if "ticker" in factor_df.columns
            else []
        )

        # Quick lookup: which tickers have ParquetStore data?
        try:
            available_tickers = set(self._store.list_tickers() or [])
        except Exception:
            available_tickers = set()

        for ticker in tickers:
            ticker_str = str(ticker)
            try:
                # ── Choose data path per ticker ───────────────────────
                if ticker_str in available_tickers:
                    # ParquetStore has data → use full history path
                    signal = self.generate_signal(ticker_str)
                else:
                    # No ParquetStore data → use pre-computed factor row
                    features_row = self._get_factor_row_for_ticker(factor_df, ticker_str)
                    if features_row is None:
                        logger.debug(f"No factor row found for {ticker_str}, skipping")
                        continue
                    signal = self.generate_signal(ticker_str, features_row=features_row)

                strength = float(signal.get("signal", 0) or 0)
                confidence = float(signal.get("confidence", 0) or 0)
                if abs(strength) >= min_threshold and confidence >= min_confidence:
                    # Get latest price from ParquetStore for risk check
                    price = 0.0
                    try:
                        df_t = self._store.read_daily(ticker_str)
                        if df_t is not None and len(df_t) > 0:
                            price = float(df_t["close"].iloc[-1])
                    except Exception:
                        pass
                    all_signals.append({
                        "ticker": ticker_str,
                        "signal": round(strength, 4),
                        "confidence": round(confidence, 4),
                        "direction": signal.get("direction", "HOLD"),
                        "price": price,
                        "close": price,
                        "components": signal.get("components", {}),
                    })
            except Exception as e:
                logger.warning(f"Inference failed for {ticker_str}: {e}")

        # Top-N selection by |signal| descending
        all_signals.sort(key=lambda s: abs(s["signal"]), reverse=True)
        return all_signals[:top_n]

    def _generate_signals_from_tickers(
        self,
        tickers: list[str],
        min_threshold: float = 0.03,
        min_confidence: float = 0.3,
        top_n: int = 5,
    ) -> list[dict[str, Any]]:
        """Generate signals from a list of ticker symbols with Top-N selection."""
        all_signals: list[dict[str, Any]] = []
        for ticker in tickers:
            try:
                signal = self.generate_signal(ticker)
                strength = float(signal.get("signal", 0) or 0)
                confidence = float(signal.get("confidence", 0) or 0)
                if abs(strength) >= min_threshold and confidence >= min_confidence:
                    price = 0.0
                    try:
                        df_t = self._store.read_daily(str(ticker))
                        if df_t is not None and len(df_t) > 0:
                            price = float(df_t["close"].iloc[-1])
                    except Exception:
                        pass
                    all_signals.append({
                        "ticker": str(ticker),
                        "signal": round(strength, 4),
                        "confidence": round(confidence, 4),
                        "direction": signal.get("direction", "HOLD"),
                        "price": price,
                        "close": price,
                        "components": signal.get("components", {}),
                    })
            except Exception as e:
                logger.error(f"Signal failed for {ticker}: {e}")

        # Top-N selection by |signal| descending
        all_signals.sort(key=lambda s: abs(s["signal"]), reverse=True)
        return all_signals[:top_n]

    def update_weights(self, model_predictions: dict[str, np.ndarray],
                       realized_returns: np.ndarray) -> dict[str, float]:
        """Update Bayesian ensemble weights with new realized data.

        Args:
            model_predictions: Dict of model → prediction arrays.
            realized_returns: Realized returns array.

        Returns:
            Updated weights.
        """
        return self.bayesian.update(model_predictions, realized_returns)

    def set_market_state(self, returns: np.ndarray) -> int:
        """Update market state detection with latest returns.

        Args:
            returns: Daily returns array.

        Returns:
            Current regime.
        """
        return self.market_state.fit(returns)
