"""services/model_infer_service/model_registry.py – Model registry for loading production models.

Queries MLflow for latest production versions and caches model metadata.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from loguru import logger

from services.model_infer_service.config import infer_config
from services.model_train_service.mlflow_manager import MLflowManager


class ModelRegistry:
    """Registry of production models with metadata caching.

    Attributes:
        cache_ttl: Time-to-live for model metadata cache in seconds.
    """

    MODEL_TYPES: tuple[str, ...] = ("gbdt", "transformer", "tcn", "tft", "rl")

    def __init__(self) -> None:
        self._mlflow = MLflowManager()
        self._cache: dict[str, dict[str, Any]] = {}
        self._last_refresh: float = 0.0
        self._cache_ttl = infer_config.MODEL_CACHE_TTL_SECONDS

    def refresh(self) -> dict[str, dict[str, Any]]:
        """Refresh model metadata from MLflow.

        Returns:
            Dict of model_type → metadata.
        """
        if time.time() - self._last_refresh < self._cache_ttl and self._cache:
            return self._cache

        result: dict[str, dict[str, Any]] = {}

        for model_type in self.MODEL_TYPES:
            model_uri = self._mlflow.get_latest_production_model(model_type)
            if model_uri:
                result[model_type] = {
                    "model_uri": model_uri,
                    "status": "production",
                    "model_type": model_type,
                }
            else:
                # Check staging (mlflow may not be installed)
                try:
                    import mlflow
                    client = mlflow.tracking.MlflowClient()
                    versions = client.get_latest_versions(
                        f"quant-{model_type}", stages=["staging"]
                    )
                    if versions:
                        result[model_type] = {
                            "model_uri": f"models:/quant-{model_type}/{versions[0].version}",
                            "status": "staging",
                            "model_type": model_type,
                        }
                    else:
                        result[model_type] = {
                            "model_uri": None,
                            "status": "not_found",
                            "model_type": model_type,
                        }
                except Exception:
                    result[model_type] = {
                        "model_uri": None,
                        "status": "not_found",
                        "model_type": model_type,
                    }

        self._cache = result
        self._last_refresh = time.time()
        logger.info(f"Model registry refreshed: {len(result)} types")
        return result

    def get(self, model_type: str) -> dict[str, Any]:
        """Get metadata for a specific model type.

        Args:
            model_type: One of 'gbdt', 'transformer', 'tcn', 'tft', 'rl'.

        Returns:
            Model metadata dict.
        """
        cache = self.refresh()
        return cache.get(model_type, {"model_uri": None, "status": "not_found"})

    def get_available_models(self) -> list[str]:
        """Get list of model types with available production models.

        Returns:
            List of model type strings.
        """
        cache = self.refresh()
        return [
            mt for mt, info in cache.items()
            if info.get("model_uri") is not None
        ]

    def get_model_path(self, model_type: str) -> Optional[str]:
        """Get local filesystem path for a model checkpoint.

        Args:
            model_type: Model type.

        Returns:
            File path to model checkpoint or None.
        """
        import os
        from services.model_train_service.config import train_config

        # Check local checkpoint first
        checkpoint_dir = train_config.MODEL_SAVE_DIR
        checkpoint_path = os.path.join(checkpoint_dir, f"{model_type}_latest.pkl")

        if os.path.exists(checkpoint_path):
            return checkpoint_path

        # Check alternatives
        for ext in [".pkl", ".pt", ".ckpt"]:
            alt_path = os.path.join(checkpoint_dir, f"{model_type}{ext}")
            if os.path.exists(alt_path):
                return alt_path

        return None
