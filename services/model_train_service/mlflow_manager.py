"""services/model_train_service/mlflow_manager.py – MLflow integration manager.

Wraps MLflow tracking: start_run, log_params, log_metrics, log_model,
register_model with stage transitions (staging → production).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Optional

from loguru import logger

from configs.settings import settings
from services.model_train_service.config import train_config


class MLflowManager:
    """MLflow experiment tracking and model registry manager.

    Provides context-managed runs with automatic logging and registration.

    Attributes:
        tracking_uri: MLflow tracking server URI.
        artifact_root: Artifact storage location.
        experiment_name: Default experiment name.
    """

    def __init__(
        self,
        tracking_uri: str | None = None,
        experiment_name: str = "quant-ai-trader-v2",
    ) -> None:
        self.tracking_uri = tracking_uri or settings.MLFLOW_TRACKING_URI
        self.artifact_root = settings.MLFLOW_ARTIFACT_ROOT
        self.experiment_name = experiment_name
        self._active_run: Any = None
        self._mlflow_available = False

        try:
            import mlflow

            # Set server timeout to avoid blocking when MLflow is unreachable
            import os
            os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "5")
            os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "1")

            mlflow.set_tracking_uri(self.tracking_uri)
            try:
                mlflow.set_experiment(self.experiment_name)
            except Exception:
                pass  # MLflow server unreachable
            self._mlflow_available = True
            logger.info(f"MLflow connected: {self.tracking_uri}")
        except ImportError:
            logger.warning("mlflow not installed — tracking disabled")
        except Exception as e:
            logger.warning(f"MLflow connection failed: {e}")

    @contextmanager
    def start_run(self, run_name: str = "") -> Iterator[Any]:
        """Context manager for MLflow run lifecycle.

        Usage:
            with mlflow_mgr.start_run("gbdt_train_001") as run:
                mlflow_mgr.log_params(params)
                mlflow_mgr.log_metrics(metrics)

        Args:
            run_name: Human-readable run name.

        Yields:
            The active MLflow run object.
        """
        if not self._mlflow_available:
            yield _MockRun()
            return

        import mlflow

        try:
            run = mlflow.start_run(run_name=run_name)
            self._active_run = run
            yield run
        except Exception as e:
            logger.error(f"MLflow run failed: {e}")
            yield _MockRun()
        finally:
            try:
                mlflow.end_run()
            except Exception:
                pass
            self._active_run = None

    def log_params(self, params: dict[str, Any]) -> None:
        """Log hyperparameters to the active MLflow run.

        Args:
            params: Dictionary of parameter name → value.
        """
        if not self._mlflow_available:
            return

        import mlflow

        try:
            for key, value in params.items():
                safe_key = str(key)[:250]
                safe_value = str(value)[:500] if not isinstance(value, (int, float)) else value
                mlflow.log_param(safe_key, safe_value)
        except Exception as e:
            logger.debug(f"Failed to log params: {e}")

    def log_metrics(self, metrics: dict[str, float], step: int | None = None) -> None:
        """Log metrics to the active MLflow run.

        Args:
            metrics: Dictionary of metric name → value.
            step: Optional step/epoch number.
        """
        if not self._mlflow_available:
            return

        import mlflow

        try:
            for key, value in metrics.items():
                safe_key = str(key)[:250]
                mlflow.log_metric(safe_key, float(value), step=step)
        except Exception as e:
            logger.debug(f"Failed to log metrics: {e}")

    def log_model(
        self,
        model: Any,
        artifact_path: str = "model",
    ) -> None:
        """Log a model artifact to MLflow.

        Args:
            model: The model object to log.
            artifact_path: Subdirectory for the artifact.
        """
        if not self._mlflow_available:
            return

        import mlflow

        try:
            # Try sklearn/pyfunc first
            if hasattr(model, "predict"):
                mlflow.sklearn.log_model(model, artifact_path)
            else:
                mlflow.pyfunc.log_model(artifact_path, python_model=_PyFuncModel(model))
        except Exception as e:
            logger.error(f"Failed to log model: {e}")

    def register_model(
        self,
        run_id: str,
        model_name: str,
        stage: str | None = None,
    ) -> Optional[int]:
        """Register a logged model to the MLflow Model Registry.

        Args:
            run_id: MLflow run ID.
            model_name: Name for the registered model.
            stage: Initial stage (default from config).

        Returns:
            Model version number or None.
        """
        if not self._mlflow_available:
            return None

        import mlflow

        try:
            stage = stage or train_config.MODEL_REGISTRY_STAGE
            artifact_uri = f"runs:/{run_id}/model"

            result = mlflow.register_model(
                model_uri=artifact_uri,
                name=f"quant-{model_name}",
            )
            logger.info(f"Registered model {model_name} v{result.version}")

            # Transition to staging → production
            client = mlflow.tracking.MlflowClient()
            client.transition_model_version_stage(
                name=f"quant-{model_name}",
                version=result.version,
                stage="staging",
            )
            client.transition_model_version_stage(
                name=f"quant-{model_name}",
                version=result.version,
                stage="production",
            )

            return result.version

        except Exception as e:
            logger.error(f"Failed to register model: {e}")
            return None

    def list_registered_models(self) -> list[dict[str, Any]]:
        """List all registered models with their versions.

        Returns:
            List of model metadata dictionaries.
        """
        if not self._mlflow_available:
            return []

        try:
            import mlflow

            client = mlflow.tracking.MlflowClient()
            models = client.search_registered_models()

            result = []
            for rm in models:
                versions = []
                for mv in rm.latest_versions:
                    versions.append({
                        "version": mv.version,
                        "stage": mv.stage,
                        "run_id": mv.run_id,
                        "status": mv.status,
                    })
                result.append({
                    "name": rm.name,
                    "latest_versions": versions,
                    "description": rm.description or "",
                })
            return result

        except Exception as e:
            logger.error(f"Failed to list models: {e}")
            return []

    # ── Stage transition helpers ────────────────────────

    def promote_to_production(
        self,
        model_name: str,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Promote a model version from staging to production.

        Finds the latest staging version and promotes it to production.
        The previous production version is demoted to archived.

        Args:
            model_name: Registered model name (without 'quant-' prefix).
            run_id: Optional run ID for fallback registration.

        Returns:
            Dict with model, version, stage keys on success; error key on failure.
        """
        if not self._mlflow_available:
            return {"error": "MLflow not available"}

        import mlflow
        from mlflow.tracking import MlflowClient

        client = MlflowClient()
        full_name = f"quant-{model_name}"

        # Find latest staging version
        staging_versions = client.get_latest_versions(full_name, stages=["Staging"])
        if not staging_versions:
            logger.warning(f"No staging version found for {full_name}")
            # Fallback: transition first available version to production
            if run_id:
                try:
                    all_versions = client.search_model_versions(
                        f"name='{full_name}'"
                    )
                    if all_versions:
                        v = all_versions[0]
                        client.transition_model_version_stage(
                            name=full_name, version=v.version, stage="Production",
                        )
                        logger.info(
                            f"Fallback: promoted {full_name} v{v.version} → Production"
                        )
                        return {"model": model_name, "version": int(v.version), "stage": "Production"}
                except Exception as e:
                    logger.warning(f"Fallback promotion failed: {e}")
            return {"error": "No staging version found"}

        for sv in staging_versions:
            # Demote current production → archived
            prod_versions = client.get_latest_versions(full_name, stages=["Production"])
            for pv in prod_versions:
                try:
                    client.transition_model_version_stage(
                        name=full_name, version=pv.version, stage="Archived",
                    )
                    logger.info(f"Archived previous production: {full_name} v{pv.version}")
                except Exception as e:
                    logger.warning(f"Failed to archive production v{pv.version}: {e}")

            # Promote staging → production
            client.transition_model_version_stage(
                name=full_name, version=sv.version, stage="Production",
            )
            logger.info(f"Promoted {full_name} v{sv.version} → Production")
            return {"model": model_name, "version": int(sv.version), "stage": "Production"}

        return {"error": "No staging version found"}

    def register_and_promote(
        self,
        model_name: str,
        model_path: str,
        run_id: str,
        metrics: dict[str, float],
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Complete MLflow pipeline: register → staging → production.

        Logs model artifact, registers it, transitions through staging
        to production in one atomic call.

        Args:
            model_name: Name for the registered model.
            model_path: Local path to the saved model file/dir.
            run_id: MLflow run ID to associate with.
            metrics: Training metrics dict.
            params: Hyperparameter dict.

        Returns:
            Dict with model, registered, promoted keys.
        """
        if not self._mlflow_available:
            return {"error": "MLflow not available", "model": model_name}

        import mlflow

        # Log params and metrics under the target run
        with mlflow.start_run(run_id=run_id):
            self.log_params(params)
            self.log_metrics(metrics)

            # Determine log model strategy based on file extension
            model_path_lower = model_path.lower()
            if model_path_lower.endswith(".pt") or model_path_lower.endswith(".pth"):
                try:
                    import torch
                    loaded = torch.load(model_path, map_location="cpu")
                    # If it's a state dict, wrap it
                    if isinstance(loaded, dict):
                        mlflow.pytorch.log_model(
                            pytorch_model=loaded,
                            artifact_path="models",
                            registered_model_name=f"quant-{model_name}",
                        )
                    else:
                        mlflow.pytorch.log_model(
                            pytorch_model=loaded,
                            artifact_path="models",
                            registered_model_name=f"quant-{model_name}",
                        )
                except Exception:
                    mlflow.log_artifact(model_path, artifact_path="models")
                    result = mlflow.register_model(
                        model_uri=f"runs:/{run_id}/models",
                        name=f"quant-{model_name}",
                    )
            elif model_path_lower.endswith(".joblib"):
                try:
                    import joblib
                    sk_model = joblib.load(model_path)
                    result = mlflow.sklearn.log_model(
                        sk_model=sk_model,
                        artifact_path="models",
                        registered_model_name=f"quant-{model_name}",
                    )
                except Exception:
                    mlflow.log_artifact(model_path, artifact_path="models")
            else:
                mlflow.log_artifact(model_path, artifact_path="models")

        # Transition to staging first, then promote to production
        try:
            register_result = mlflow.register_model(
                model_uri=f"runs:/{run_id}/models",
                name=f"quant-{model_name}",
            )
        except Exception:
            # Model may already be registered — promote existing
            register_result = None

        promote_result = self.promote_to_production(model_name, run_id)

        return {
            "model": model_name,
            "registered": str(register_result) if register_result else "already_exists",
            "promoted": promote_result,
        }

    def get_latest_production_model(self, model_name: str) -> Optional[str]:
        """Get the run_id of the latest production model.

        Args:
            model_name: Registered model name.

        Returns:
            Model URI string or None.
        """
        if not self._mlflow_available:
            return None

        try:
            import mlflow

            client = mlflow.tracking.MlflowClient()
            versions = client.get_latest_versions(f"quant-{model_name}", stages=["production"])

            if versions:
                version = versions[0]
                return f"models:/quant-{model_name}/{version.version}"
            return None

        except Exception as e:
            logger.error(f"Failed to get production model: {e}")
            return None


class _PyFuncModel:
    """Simple pyfunc wrapper."""

    def __init__(self, model: Any) -> None:
        self._model = model

    def predict(self, context: Any, model_input: Any) -> Any:
        import numpy as np
        return self._model.predict(model_input)


class _MockRun:
    """Mock MLflow run for when MLflow is not available."""
    info = type("info", (), {"run_id": "mock-run-id"})()

    def __enter__(self) -> "_MockRun":
        return self

    def __exit__(self, *args: Any) -> None:
        pass
