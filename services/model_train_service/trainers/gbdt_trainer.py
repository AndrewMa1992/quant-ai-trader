"""services/model_train_service/trainers/gbdt_trainer.py – GBDT trainer.

Supports XGBoost, LightGBM, and CatBoost.
GPU-ready when available. Early stopping built-in.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import numpy as np
import pandas as pd
from loguru import logger

from services.model_train_service.config import train_config
from services.model_train_service.trainers.trainer_base import TrainerBase


class GBDTTrainer(TrainerBase):
    """Gradient-boosted decision tree trainer.

    Default: LightGBM. Also supports XGBoost and CatBoost.

    Attributes:
        gbdt_type: One of 'lightgbm', 'xgboost', 'catboost'.
        params: Model hyperparameter dictionary.
    """

    model_name = "gbdt"

    def __init__(
        self,
        gbdt_type: str = "lightgbm",
        params: dict[str, Any] | None = None,
        device: str | None = None,
    ) -> None:
        super().__init__(device=device or train_config.DEVICE)
        self.gbdt_type = gbdt_type.lower()
        self.params = params or self._default_params()

    def _default_params(self) -> dict[str, Any]:
        """Return default hyperparameters based on GBDT type."""
        base = {
            "lightgbm": {
                "objective": "regression",
                "metric": "rmse",
                "num_leaves": 31,
                "learning_rate": 0.05,
                "feature_fraction": 0.8,
                "bagging_fraction": 0.8,
                "bagging_freq": 5,
                "verbose": -1,
                "n_estimators": 500,
                "early_stopping_rounds": 20,
            },
            "xgboost": {
                "objective": "reg:squarederror",
                "eval_metric": "rmse",
                "learning_rate": 0.05,
                "max_depth": 6,
                "subsample": 0.8,
                "colsample_bytree": 0.8,
                "n_estimators": 500,
                "early_stopping_rounds": 20,
                "verbosity": 0,
            },
            "catboost": {
                "loss_function": "RMSE",
                "learning_rate": 0.05,
                "depth": 6,
                "subsample": 0.8,
                "iterations": 500,
                "early_stopping_rounds": 20,
                "verbose": False,
                "allow_writing_files": False,
            },
        }
        return base.get(self.gbdt_type, base["lightgbm"])

    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        X_valid: pd.DataFrame | None = None,
        y_valid: pd.Series | None = None,
        **kwargs: Any,
    ) -> dict[str, float]:
        """Train the GBDT model.

        Args:
            X: Training features.
            y: Training target.
            X_valid: Validation features.
            y_valid: Validation target.
            **kwargs: Override default hyperparameters.

        Returns:
            Training metrics dictionary.
        """
        self._validate_data(X, y)
        params = {**self.params, **kwargs}

        # Split validation if not provided
        if X_valid is None:
            split_idx = int(len(X) * 0.8)
            X_valid = X.iloc[split_idx:]
            y_valid = y.iloc[split_idx:]
            X = X.iloc[:split_idx]
            y = y.iloc[:split_idx]

        if self.gbdt_type == "lightgbm":
            metrics = self._fit_lightgbm(X, y, X_valid, y_valid, params)
        elif self.gbdt_type == "xgboost":
            metrics = self._fit_xgboost(X, y, X_valid, y_valid, params)
        elif self.gbdt_type == "catboost":
            metrics = self._fit_catboost(X, y, X_valid, y_valid, params)
        else:
            raise ValueError(f"Unknown GBDT type: {self.gbdt_type}")

        logger.info(f"GBDT ({self.gbdt_type}) training metrics: {metrics}")
        return metrics

    def _fit_lightgbm(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        X_valid: pd.DataFrame,
        y_valid: pd.Series,
        params: dict[str, Any],
    ) -> dict[str, float]:
        """Fit using LightGBM."""
        try:
            import lightgbm as lgb

            train_data = lgb.Dataset(X, label=y)
            valid_data = lgb.Dataset(X_valid, label=y_valid, reference=train_data)

            n_estimators = params.pop("n_estimators", 500)
            early_stopping = params.pop("early_stopping_rounds", 20)

            self.model = lgb.train(
                params,
                train_data,
                valid_sets=[train_data, valid_data],
                valid_names=["train", "valid"],
                num_boost_round=n_estimators,
                callbacks=[lgb.early_stopping(early_stopping), lgb.log_evaluation(0)],
            )

            pred = self.model.predict(X_valid)
            rmse = float(np.sqrt(((pred - y_valid.values) ** 2).mean()))
            return {
                "train_rmse": float(np.sqrt(((self.model.predict(X) - y.values) ** 2).mean())),
                "val_rmse": rmse,
                "best_iteration": self.model.best_iteration,
            }

        except ImportError:
            return self._fit_sklearn_fallback(X, y, X_valid, y_valid)

    def _fit_xgboost(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        X_valid: pd.DataFrame,
        y_valid: pd.Series,
        params: dict[str, Any],
    ) -> dict[str, float]:
        """Fit using XGBoost."""
        try:
            import xgboost as xgb

            n_estimators = params.pop("n_estimators", 500)
            early_stopping = params.pop("early_stopping_rounds", 20)

            self.model = xgb.XGBRegressor(**params, n_estimators=n_estimators)
            self.model.fit(
                X, y,
                eval_set=[(X_valid, y_valid)],
                verbose=False,
            )

            train_pred = self.model.predict(X)
            val_pred = self.model.predict(X_valid)

            return {
                "train_rmse": float(np.sqrt(((train_pred - y.values) ** 2).mean())),
                "val_rmse": float(np.sqrt(((val_pred - y_valid.values) ** 2).mean())),
            }

        except ImportError:
            return self._fit_sklearn_fallback(X, y, X_valid, y_valid)

    def _fit_catboost(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        X_valid: pd.DataFrame,
        y_valid: pd.Series,
        params: dict[str, Any],
    ) -> dict[str, float]:
        """Fit using CatBoost."""
        try:
            from catboost import CatBoostRegressor

            iterations = params.pop("iterations", 500)
            early_stopping = params.pop("early_stopping_rounds", 20)

            self.model = CatBoostRegressor(**params, iterations=iterations)
            self.model.fit(
                X, y,
                eval_set=(X_valid, y_valid),
                verbose=False,
            )

            train_pred = self.model.predict(X)
            val_pred = self.model.predict(X_valid)

            return {
                "train_rmse": float(np.sqrt(((train_pred - y.values) ** 2).mean())),
                "val_rmse": float(np.sqrt(((val_pred - y_valid.values) ** 2).mean())),
            }

        except ImportError:
            return self._fit_sklearn_fallback(X, y, X_valid, y_valid)

    def _fit_sklearn_fallback(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        X_valid: pd.DataFrame,
        y_valid: pd.Series,
    ) -> dict[str, float]:
        """Fallback: use sklearn GradientBoostingRegressor."""
        from sklearn.ensemble import GradientBoostingRegressor

        self.model = GradientBoostingRegressor(
            n_estimators=200,
            learning_rate=0.05,
            max_depth=5,
            subsample=0.8,
            random_state=42,
        )
        self.model.fit(X, y)

        train_pred = self.model.predict(X)
        val_pred = self.model.predict(X_valid)

        return {
            "train_rmse": float(np.sqrt(((train_pred - y.values) ** 2).mean())),
            "val_rmse": float(np.sqrt(((val_pred - y_valid.values) ** 2).mean())),
        }

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Generate predictions.

        Args:
            X: Feature matrix.

        Returns:
            Numpy array of predictions.
        """
        if self.model is None:
            raise RuntimeError("Model not trained. Call fit() first.")

        X_arr = self._to_numpy(X)
        pred = self.model.predict(X_arr)
        return np.array(pred).ravel()

    def get_feature_importance(self) -> pd.Series:
        """Get feature importance from GBDT model.

        Returns:
            Series of feature importance scores.
        """
        if self.model is None:
            return pd.Series(dtype=float)

        if not self._feature_names:
            return pd.Series(dtype=float)

        if self.gbdt_type == "lightgbm" and hasattr(self.model, "feature_importance"):
            importance = self.model.feature_importance(importance_type="gain")
            return pd.Series(importance, index=self._feature_names).sort_values(ascending=False)
        elif hasattr(self.model, "feature_importances_"):
            return pd.Series(
                self.model.feature_importances_,
                index=self._feature_names[:len(self.model.feature_importances_)],
            ).sort_values(ascending=False)

        return super().get_feature_importance()

    def save(self, path: str) -> None:
        """Save model to disk.

        Args:
            path: File path.
        """
        import joblib
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        joblib.dump({"model": self.model, "gbdt_type": self.gbdt_type,
                      "feature_names": self._feature_names}, path)
        logger.info(f"GBDT model saved to {path}")

    def load(self, path: str) -> None:
        """Load model from disk.

        Args:
            path: File path.
        """
        import joblib
        data = joblib.load(path)
        self.model = data["model"]
        self.gbdt_type = data.get("gbdt_type", "lightgbm")
        self._feature_names = data.get("feature_names", [])
        self.loaded = True
        logger.info(f"GBDT model loaded from {path}")
