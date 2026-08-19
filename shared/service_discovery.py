"""shared/service_discovery.py – Resolve microservice hosts for local and Docker.

Local default: 127.0.0.1
Docker: set QAT_USE_DOCKER=true and/or QAT_SVC_*_HOST overrides.
"""

from __future__ import annotations

import os
from typing import Dict


SERVICE_PORT_MAP: Dict[str, int] = {
    "data": int(os.getenv("QAT_DATA_PORT", "8011")),
    "factor": int(os.getenv("QAT_FACTOR_PORT", "8012")),
    "model_train": int(os.getenv("QAT_MODEL_TRAIN_PORT", "8013")),
    "model_infer": int(os.getenv("QAT_MODEL_INFER_PORT", "8014")),
    "risk": int(os.getenv("QAT_RISK_PORT", "8015")),
    "execution": int(os.getenv("QAT_EXEC_PORT", "8016")),
}

# Compose service DNS names when running under Docker
_DOCKER_HOST_DEFAULTS: Dict[str, str] = {
    "data": "data-service",
    "factor": "factor-service",
    "model_train": "model-train",
    "model_infer": "model-infer",
    "risk": "risk-service",
    "execution": "execution-service",
}

_ENV_HOST_KEYS: Dict[str, str] = {
    "data": "QAT_SVC_DATA_HOST",
    "factor": "QAT_SVC_FACTOR_HOST",
    "model_train": "QAT_SVC_MODEL_TRAIN_HOST",
    "model_infer": "QAT_SVC_MODEL_INFER_HOST",
    "risk": "QAT_SVC_RISK_HOST",
    "execution": "QAT_SVC_EXEC_HOST",
}


def use_docker() -> bool:
    return os.getenv("QAT_USE_DOCKER", "false").strip().lower() in ("1", "true", "yes", "on")


def service_host(name: str) -> str:
    """Return hostname for a canonical microservice name."""
    env_key = _ENV_HOST_KEYS.get(name)
    if env_key:
        override = os.getenv(env_key, "").strip()
        if override:
            return override
    if use_docker():
        return _DOCKER_HOST_DEFAULTS.get(name, "127.0.0.1")
    return "127.0.0.1"


def service_port(name: str) -> int:
    return int(SERVICE_PORT_MAP.get(name, 0))


def service_base_url(name: str) -> str:
    """Return http://host:port for a microservice."""
    return f"http://{service_host(name)}:{service_port(name)}"


def service_health_url(name: str) -> str:
    return f"{service_base_url(name)}/health"
