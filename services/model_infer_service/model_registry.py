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

        Scans both the configured model save directory and data/models/
        for checkpoint files. Supports versioned file naming (v1, v2, ...)
        and returns the highest version found.

        Args:
            model_type: Model type.

        Returns:
            File path to model checkpoint or None.
        """
        import glob
        import os
        import re
        from services.model_train_service.config import train_config

        checkpoint_dir = train_config.MODEL_SAVE_DIR
        search_dirs: list[str] = [
            os.path.abspath(checkpoint_dir),
            os.path.abspath(os.path.join("data", "models")),
        ]
        extensions: tuple[str, ...] = (".pkl", ".pt", ".ckpt", ".joblib")

        candidates: list[tuple[int, str]] = []  # (version, path)

        for search_dir in search_dirs:
            if not os.path.isdir(search_dir):
                continue

            # 1) Check {model_type}_latest.pkl
            latest_path = os.path.join(search_dir, f"{model_type}_latest.pkl")
            if os.path.exists(latest_path):
                candidates.append((999999, latest_path))  # "latest" trumps all

            # 2) Check exact {model_type}{ext}
            for ext in extensions:
                exact_path = os.path.join(search_dir, f"{model_type}{ext}")
                if os.path.exists(exact_path):
                    candidates.append((0, exact_path))

            # 3) Scan for {model_type}_v* patterns
            for ext in extensions:
                pattern = os.path.join(search_dir, f"{model_type}_v*{ext}")
                for match in glob.glob(pattern):
                    basename = os.path.basename(match)
                    # Extract version number from e.g. "gbdt_v2.joblib"
                    m = re.search(r"_v(\d+)", basename)
                    if m:
                        version = int(m.group(1))
                        candidates.append((version, match))

        if not candidates:
            return None

        # Sort by version descending, pick highest
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_version, best_path = candidates[0]
        logger.debug(
            f"get_model_path({model_type}): selected v{best_version} at {best_path}"
        )
        return best_path
