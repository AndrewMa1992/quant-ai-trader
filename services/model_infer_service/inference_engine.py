"""services/model_infer_service/inference_engine.py – Central inference engine.

Orchestrates: load models → preprocess → multi-model inference → ensemble → signal.

Signal format per ticker:
- signal: float ∈ [-1, 1] (positive=buy, negative=sell, 0=hold)
- confidence: float ∈ [0, 1]
- direction: 'BUY' / 'SELL' / 'HOLD'
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
            df[f"ret_{p}d"] = df[col].pct_change(p)

    def predict_single(self, ticker: str) -> dict[str, Any]:
        """Run all loaded models on a single ticker.

        Uses ``FactorEngine`` to compute the same 77-feature set that was
        used during training. If FactorEngine is unavailable, falls back to
        basic return features (which will likely cause shape-mismatch errors
        in trained models, but at least avoids hard crashes).

        Args:
            ticker: Stock ticker symbol.

        Returns:
            Dict with per-model predictions.
        """
        # Load data
        df = self._store.read_daily(ticker)
        if df is None or len(df) < 100:
            logger.warning(f"Insufficient data for {ticker}")
            return {
                "ticker": ticker,
                "predictions": {},
                "error": "Insufficient data",
            }

        df = df.tail(504).copy()  # 2 years of daily data for sufficient context

        # Compute full feature set using FactorEngine (same as training).
        if self._factor_engine is not None:
            try:
                df = self._factor_engine.compute_all(df)
            except Exception as e:
                logger.warning(
                    f"FactorEngine failed for {ticker}, using basic features: {e}"
                )
                self._compute_basic_returns(df)
        else:
            # Fallback: basic returns if FactorEngine not available
            self._compute_basic_returns(df)

        # Compute basic return columns (training included these alongside factors)
        self._compute_basic_returns(df)

        # Align columns to match exact training order (77 features).
        # Training order: close, high, low, open, volume, ret_1d..ret_63d, F001..F311
        train_cols = self._feature_names
        aligned = pd.DataFrame(0.0, index=df.index, columns=train_cols)
        for col in train_cols:
            if col in df.columns:
                aligned[col] = df[col].values
            # If col not in df.columns, it stays 0.0 (missing feature)
        missing = [c for c in train_cols if c not in df.columns]
        if missing:
            logger.debug(f"Missing features for {ticker} (padded=0): {missing[:5]}...")

        X = aligned.fillna(0.0).tail(252)

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

    def generate_signal(self, ticker: str) -> dict[str, Any]:
        """Generate a trading signal for a ticker.

        Orchestrates the full pipeline: load → predict → blend → signal.

        Args:
            ticker: Stock ticker.

        Returns:
            Signal dict with signal, confidence, direction, components.
        """
        result = self.predict_single(ticker)
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
        min_threshold: float = 0.05,
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

    def _generate_signals_from_factor_df(
        self,
        factor_df: pd.DataFrame,
        min_threshold: float = 0.05,
        min_confidence: float = 0.3,
        top_n: int = 5,
    ) -> list[dict[str, Any]]:
        """Generate signals from FactorEngine-computed factor DataFrame.

        Full inference on all tickers, then Top-N selection by |signal| desc.

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

        for ticker in tickers:
            try:
                signal = self.generate_signal(str(ticker))
                strength = float(signal.get("signal", 0) or 0)
                confidence = float(signal.get("confidence", 0) or 0)
                if abs(strength) >= min_threshold and confidence >= min_confidence:
                    # Get latest price from ParquetStore for risk check
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
                logger.warning(f"Inference failed for {ticker}: {e}")

        # Top-N selection by |signal| descending
        all_signals.sort(key=lambda s: abs(s["signal"]), reverse=True)
        return all_signals[:top_n]

    def _generate_signals_from_tickers(
        self,
        tickers: list[str],
        min_threshold: float = 0.05,
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
