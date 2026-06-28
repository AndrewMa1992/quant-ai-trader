"""services/model_infer_service/models/gbdt_model.py – GBDT inference wrapper.

Loads XGBoost/LightGBM/CatBoost models, outputs directional probability.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger


class GBDTInference:
    """GBDT inference wrapper.

    Attributes:
        model_name: 'gbdt'
        loaded: Whether a model is loaded.
    """

    model_name = "gbdt"

    def __init__(self) -> None:
        self.model: object | None = None
        self.loaded: bool = False
        self._gbdt_type: str = "lightgbm"
        self._feature_names: list[str] = []

    def load(self, path: str) -> bool:
        """Load model from checkpoint.

        Args:
            path: File path to saved model.

        Returns:
            True if loaded successfully.
        """
        try:
            import joblib
            data = joblib.load(path)

            if isinstance(data, dict):
                self.model = data.get("model")
                self._gbdt_type = data.get("gbdt_type", "lightgbm")
                self._feature_names = data.get("feature_names", [])
            else:
                self.model = data

            self.loaded = self.model is not None
            if self.loaded:
                logger.info(f"GBDT model loaded from {path}")
            return self.loaded

        except Exception as e:
            logger.error(f"Failed to load GBDT model: {e}")
            return False

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Generate predictions.

        Args:
            X: Feature matrix.

        Returns:
            Prediction values.
        """
        if not self.loaded or self.model is None:
            return np.zeros(len(X))

        X_arr = X.values.astype(np.float32)

        if hasattr(self.model, "predict"):
            raw = self.model.predict(X_arr, predict_disable_shape_check=True)
        else:
            raw = np.zeros(len(X_arr))

        return np.array(raw).ravel()

    def predict_direction_prob(self, X: pd.DataFrame) -> dict[str, np.ndarray]:
        """Return directional probability (up/down).

        Args:
            X: Feature matrix.

        Returns:
            Dict with 'up_prob', 'down_prob', 'value' arrays.
        """
        raw = self.predict(X)

        # Sigmoid to get probabilities
        up_prob = 1.0 / (1.0 + np.exp(-raw * 2.0))
        down_prob = 1.0 - up_prob

        return {
            "up_prob": up_prob,
            "down_prob": down_prob,
            "value": raw,
        }
