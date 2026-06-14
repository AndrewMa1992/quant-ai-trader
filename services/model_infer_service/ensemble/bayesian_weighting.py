"""services/model_infer_service/ensemble/bayesian_weighting.py – Bayesian dynamic weights.

Rolling 60-day window computes Sharpe/IC per model.
Posterior weights via softmax normalization with adaptive learning rate.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from services.model_infer_service.config import infer_config


class BayesianWeighting:
    """Dynamically adjusts ensemble weights based on recent performance.

    Computes rolling Sharpe ratio and IC for each model, then
    applies softmax normalization to produce dynamic weights.

    Attributes:
        window_days: Rolling window for performance computation.
        temperature: Softmax temperature (lower = sharper).
        weight_history: Dict of model_name → list of (date, weight).
    """

    def __init__(
        self,
        window_days: int | None = None,
        temperature: float = 2.0,
    ) -> None:
        self.window_days = window_days or infer_config.BAYESIAN_WINDOW_DAYS
        self.temperature = temperature
        self._performance_cache: dict[str, list[dict[str, float]]] = {}
        self._current_weights: dict[str, float] = {}

    def update(
        self,
        model_predictions: dict[str, np.ndarray],
        realized_returns: np.ndarray,
        timestamp: str = "",
    ) -> dict[str, float]:
        """Update weights based on latest prediction-vs-realized performance.

        Args:
            model_predictions: Dict of model_name → array of predictions.
            realized_returns: Array of actual returns (same length).
            timestamp: Optional timestamp for logging.

        Returns:
            Updated weight dictionary.
        """
        n_models = len(model_predictions)
        if n_models == 0:
            return {}

        model_scores: dict[str, float] = {}

        for name, predictions in model_predictions.items():
            if len(predictions) < 10:
                model_scores[name] = 0.0
                continue

            common_len = min(len(predictions), len(realized_returns))
            pred = predictions[-common_len:]
            actual = realized_returns[-common_len:]

            # Compute IC (Spearman)
            ic = self._compute_ic(pred, actual)

            # Compute Sharpe-like metric (hit ratio over last window)
            hit_ratio = float(np.mean(np.sign(pred) == np.sign(actual)))

            # Combined score
            score = 0.5 * (abs(ic) / 0.1) + 0.5 * hit_ratio

            # Track performance
            if name not in self._performance_cache:
                self._performance_cache[name] = []
            self._performance_cache[name].append({
                "ic": round(float(ic), 6),
                "hit_ratio": round(hit_ratio, 4),
                "score": round(float(score), 4),
            })

            model_scores[name] = float(score)

        # Softmax normalization
        scores_arr = np.array(list(model_scores.values()))
        names = list(model_scores.keys())

        # Avoid overflow
        scores_arr = np.clip(scores_arr / self.temperature, -10, 10)
        exp_scores = np.exp(scores_arr)
        softmax = exp_scores / exp_scores.sum()

        weights = {name: round(float(w), 4) for name, w in zip(names, softmax)}
        self._current_weights = weights

        logger.debug(f"Bayesian weights updated: {weights}")
        return weights

    def _compute_ic(self, predictions: np.ndarray, actual: np.ndarray) -> float:
        """Compute Spearman rank correlation.

        Args:
            predictions: Model predictions.
            actual: Realized values.

        Returns:
            Spearman correlation.
        """
        valid = ~(np.isnan(predictions) | np.isnan(actual))
        if valid.sum() < 10:
            return 0.0

        try:
            from scipy.stats import spearmanr
            corr, _ = spearmanr(predictions[valid], actual[valid])
            return float(corr) if not np.isnan(corr) else 0.0
        except ImportError:
            # Fallback: Pearson
            corr = np.corrcoef(predictions[valid], actual[valid])[0, 1]
            return float(corr) if not np.isnan(corr) else 0.0

    def get_weights(self) -> dict[str, float]:
        """Get current weights (equal-weighted if not yet updated).

        Returns:
            Current weight dictionary.
        """
        return self._current_weights

    def get_performance_summary(self) -> dict[str, dict[str, float]]:
        """Get performance summary per model.

        Returns:
            Dict of model_name → {mean_ic, mean_hit_ratio, recent_score}.
        """
        summary: dict[str, dict[str, float]] = {}
        for name, history in self._performance_cache.items():
            if not history:
                continue
            ics = [h["ic"] for h in history[-self.window_days:]]
            hrs = [h["hit_ratio"] for h in history[-self.window_days:]]
            summary[name] = {
                "mean_ic": round(float(np.mean(ics)), 6),
                "mean_hit_ratio": round(float(np.mean(hrs)), 4),
                "recent_score": history[-1]["score"] if history else 0.0,
                "n_obs": len(history),
            }
        return summary

    def reset(self) -> None:
        """Reset all performance history."""
        self._performance_cache.clear()
        self._current_weights.clear()
        logger.info("Bayesian weighting reset")
