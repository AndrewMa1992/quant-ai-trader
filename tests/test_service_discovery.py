"""Tests for Docker/local service discovery."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_local_defaults(monkeypatch):
    monkeypatch.delenv("QAT_USE_DOCKER", raising=False)
    for k in [
        "QAT_SVC_DATA_HOST",
        "QAT_SVC_FACTOR_HOST",
        "QAT_SVC_MODEL_TRAIN_HOST",
        "QAT_SVC_MODEL_INFER_HOST",
        "QAT_SVC_RISK_HOST",
        "QAT_SVC_EXEC_HOST",
    ]:
        monkeypatch.delenv(k, raising=False)

    import importlib
    import shared.service_discovery as sd

    importlib.reload(sd)
    assert sd.service_host("data") == "127.0.0.1"
    assert sd.service_base_url("risk").endswith(":8015")


def test_docker_hosts(monkeypatch):
    monkeypatch.setenv("QAT_USE_DOCKER", "true")
    import importlib
    import shared.service_discovery as sd

    importlib.reload(sd)
    assert sd.service_host("data") == "data-service"
    assert sd.service_host("execution") == "execution-service"
    assert "data-service:8011" in sd.service_base_url("data")


def test_env_override_wins(monkeypatch):
    monkeypatch.setenv("QAT_USE_DOCKER", "true")
    monkeypatch.setenv("QAT_SVC_DATA_HOST", "custom-data")
    import importlib
    import shared.service_discovery as sd

    importlib.reload(sd)
    assert sd.service_host("data") == "custom-data"
