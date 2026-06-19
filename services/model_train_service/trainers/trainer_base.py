"""services/model_train_service/trainers/trainer_base.py – Abstract base class for model trainers.

All trainers must implement: fit, predict, save, load, get_feature_importance.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd


class TrainerBase(ABC):
    """Abstract base class for all ML/DL model trainers.

    Subclasses implement model-specific fit/predict/save/load logic.

    Attributes:
        model: The underlying model object (set after fit).
        model_name: Human-readable model name.
        device: Compute device string (cpu/cuda/mps).
    """

    model_name: str = "base"
    model: Any = None
    device: str = "cpu"

    def __init__(self, device: str = "cpu") -> None:
        self.device = device
        self._feature_names: list[str] = []

    @abstractmethod
    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        X_valid: pd.DataFrame | None = None,
        y_valid: pd.Series | None = None,
        **kwargs: Any,
    ) -> dict[str, float]:
        """Train the model.

        Args:
            X: Feature matrix.
            y: Target vector.
            X_valid: Optional validation features.
            y_valid: Optional validation target.
            **kwargs: Model-specific hyperparameters.

        Returns:
            Dictionary of training metrics (e.g. {'loss': 0.1, 'val_loss': 0.12}).
        """
        ...

    @abstractmethod
    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Generate predictions.

        Args:
            X: Feature matrix.

        Returns:
            Numpy array of predictions.
        """
        ...

    @abstractmethod
    def save(self, path: str) -> None:
        """Save the trained model to disk.

        Args:
            path: File path for saving.
        """
        ...

    @abstractmethod
    def load(self, path: str) -> None:
        """Load a trained model from disk.

        Args:
            path: File path to the saved model.
        """
        ...

    def get_feature_importance(self) -> pd.Series:
        """Return feature importance scores.

        Returns:
            Series mapping feature name → importance score.
            Returns empty Series by default.
        """
        if not self._feature_names:
            return pd.Series(dtype=float)

        # Default: uniform importance
        return pd.Series(
            [1.0 / len(self._feature_names)] * len(self._feature_names),
            index=self._feature_names,
        )

    def _to_numpy(self, X: pd.DataFrame) -> np.ndarray:
        """Convert DataFrame to numpy array, storing feature names.

        Args:
            X: Feature DataFrame.

        Returns:
            Numpy float32 array.
        """
        self._feature_names = list(X.columns)
        return X.values.astype(np.float32)

    def _validate_data(self, X: pd.DataFrame, y: pd.Series | None = None) -> None:
        """Validate input data dimensions.

        Args:
            X: Feature matrix.
            y: Optional target.

        Raises:
            ValueError: If data is incompatible.
        """
        has_empty = (hasattr(X, 'empty') and X.empty) or (hasattr(X, 'size') and X.size == 0)
        if has_empty:
            raise ValueError("Feature matrix is empty")
        if y is not None and len(X) != len(y):
            raise ValueError(
                f"Feature/target length mismatch: {len(X)} vs {len(y)}"
            )
        if y is not None and hasattr(y, 'isna'):
            y_vals = y.values if hasattr(y, 'values') else y
            if np.isnan(y_vals).all():
                raise ValueError("Target is all NaN")

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(device={self.device})>"
