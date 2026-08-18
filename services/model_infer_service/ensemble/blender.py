"""services/model_infer_service/ensemble/blender.py – Signal fusion (blending).

Three modes:
- weighted_average: Model predictions weighted by confidence
- voting: Majority direction voting
- stacking: Meta-model layer (simple linear regression)
"""

from __future__ import annotations

from typing import Any

import numpy as np
from loguru import logger

from services.model_infer_service.config import infer_config


class SignalBlender:
    """Blends predictions from multiple models into a unified signal.

    Attributes:
        mode: Blending mode ('weighted_average', 'voting', 'stacking').
        min_confidence: Minimum confidence threshold.
    """

    def __init__(
        self,
        mode: str | None = None,
        min_confidence: float | None = None,
    ) -> None:
        self.mode = mode or infer_config.ENSEMBLE_MODE
        self.min_confidence = min_confidence or infer_config.MIN_CONFIDENCE
        self._stacking_coefs: dict[str, float] = {}
        self._stacking_intercept: float = 0.0

    def blend(
        self,
        model_predictions: dict[str, dict[str, Any]],
        weights: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Blend model predictions into a single signal.

        Args:
            model_predictions: Dict of model_name → {value, confidence, direction}.
            weights: Dict of model_name → weight (for weighted_average mode).
                     If None, uniform weights are used.

        Returns:
            Blended signal dict with 'signal', 'confidence', 'direction', 'components'.
        """
        if not model_predictions:
            return {
                "signal": 0.0,
                "confidence": 0.0,
                "direction": "HOLD",
                "components": {},
            }

        # Filter by confidence
        filtered = {
            name: pred
            for name, pred in model_predictions.items()
            if pred.get("confidence", 0) >= self.min_confidence
        }

        if not filtered:
            return {
                "signal": 0.0,
                "confidence": 0.0,
                "direction": "HOLD",
                "components": {},
            }

        if self.mode == "weighted_average":
            result = self._weighted_average(filtered, weights)
        elif self.mode == "voting":
            result = self._voting(filtered, weights)
        elif self.mode == "stacking":
            result = self._stacking(filtered)
        else:
            result = self._weighted_average(filtered, weights)

        return result

    def _weighted_average(
        self,
        predictions: dict[str, dict[str, Any]],
        weights: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Weighted average blending.

        Args:
            predictions: Filtered model predictions.
            weights: Optional model weights.

        Returns:
            Blended signal.
        """
        if weights is None:
            n = len(predictions)
            weights = {name: 1.0 / n for name in predictions}
        else:
            # Renormalize to the filtered subset so dropped models don't leak weight
            active = {k: float(v) for k, v in weights.items() if k in predictions and float(v) > 0}
            s = sum(active.values())
            if s > 0:
                weights = {k: v / s for k, v in active.items()}
            else:
                n = len(predictions)
                weights = {name: 1.0 / n for name in predictions}

        total_weight = 0.0
        weighted_signal = 0.0
        weighted_confidence = 0.0
        components: dict[str, float] = {}

        for name, pred in predictions.items():
            w = weights.get(name, 0.0)
            if w <= 0.0:
                continue

            sig = float(pred.get("value", pred.get("signal", 0.0)))
            conf = float(pred.get("confidence", 0.5))

            # Weight by model weight only (confidence already used as filter gate)
            weighted_signal += sig * w
            weighted_confidence += conf * w
            total_weight += w
            components[name] = sig

        if total_weight > 0:
            signal = weighted_signal / total_weight
            confidence = weighted_confidence / total_weight
        else:
            signal = 0.0
            confidence = 0.0

        # Clip
        signal = np.clip(signal, -infer_config.SIGNAL_CLIP, infer_config.SIGNAL_CLIP)
        confidence = np.clip(confidence, 0.0, 1.0)

        direction = "HOLD"
        if signal > 0.05:
            direction = "BUY"
        elif signal < -0.05:
            direction = "SELL"

        return {
            "signal": round(float(signal), 6),
            "confidence": round(float(confidence), 4),
            "direction": direction,
            "components": components,
        }

    def _voting(
        self,
        predictions: dict[str, dict[str, Any]],
        weights: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Majority direction voting.

        Args:
            predictions: Model predictions.
            weights: Optional vote weights.

        Returns:
            Blended signal via voting.
        """
        buy_votes = 0.0
        sell_votes = 0.0
        hold_votes = 0.0
        total = 0.0
        components: dict[str, float] = {}

        for name, pred in predictions.items():
            w = weights.get(name, 1.0) if weights else 1.0
            direction = pred.get("direction", "HOLD")
            sig = float(pred.get("value", 0.0))
            components[name] = sig

            if direction == "BUY":
                buy_votes += w
            elif direction == "SELL":
                sell_votes += w
            else:
                hold_votes += w
            total += w

        if total > 0:
            buy_pct = buy_votes / total
            sell_pct = sell_votes / total
        else:
            buy_pct = sell_pct = 0.0

        signal = buy_pct - sell_pct
        confidence = max(buy_pct, sell_pct, hold_votes / max(total, 1))

        direction = "HOLD"
        if buy_pct > sell_pct and buy_pct > 0.33:
            direction = "BUY"
        elif sell_pct > buy_pct and sell_pct > 0.33:
            direction = "SELL"

        return {
            "signal": round(float(signal), 6),
            "confidence": round(float(confidence), 4),
            "direction": direction,
            "components": components,
        }

    def _stacking(self, predictions: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """Simple linear stacking with pre-fit coefficients.

        Args:
            predictions: Model predictions.

        Returns:
            Stacked signal.
        """
        signal = 0.0
        confidence = 0.0
        components: dict[str, float] = {}

        for name, pred in predictions.items():
            sig = float(pred.get("value", 0.0))
            coef = self._stacking_coefs.get(name, 1.0 / max(len(predictions), 1))
            signal += sig * coef
            confidence += float(pred.get("confidence", 0.5)) * abs(coef)
            components[name] = sig

        signal += self._stacking_intercept
        signal = np.clip(signal, -infer_config.SIGNAL_CLIP, infer_config.SIGNAL_CLIP)
        confidence = np.clip(confidence / max(len(predictions), 1), 0.0, 1.0)

        direction = "HOLD"
        if signal > 0.05:
            direction = "BUY"
        elif signal < -0.05:
            direction = "SELL"

        return {
            "signal": round(float(signal), 6),
            "confidence": round(float(confidence), 4),
            "direction": direction,
            "components": components,
        }

    def fit_stacking(
        self,
        X: dict[str, list[float]],  # model_name → list of predictions
        y: list[float],  # true returns
    ) -> dict[str, float]:
        """Fit linear stacking coefficients.

        Args:
            X: Model predictions dict.
            y: Target returns.

        Returns:
            R-squared score.
        """
        from sklearn.linear_model import LinearRegression

        model_names = list(X.keys())
        if not model_names:
            return {"r2": 0.0}

        X_arr = np.column_stack([X[name] for name in model_names])
        reg = LinearRegression().fit(X_arr, y)

        for i, name in enumerate(model_names):
            self._stacking_coefs[name] = float(reg.coef_[i])
        self._stacking_intercept = float(reg.intercept_)

        r2 = float(reg.score(X_arr, y))
        logger.info(f"Stacking coefficients fitted: R²={r2:.4f}")
        return {"r2": r2}
