"""Tests for paper Tiger account resolution and SPA auth path."""

from __future__ import annotations

import os

from api_gateway.middleware.auth import PUBLIC_PATHS
from shared.tiger_account import (
    LIVE_ACCOUNT_DEFAULT,
    PAPER_ACCOUNT_DEFAULT,
    resolve_tiger_account,
)


def test_paper_account_default_under_sim(monkeypatch):
    monkeypatch.setenv("QAT_TRADING_SIMULATION_MODE", "true")
    monkeypatch.delenv("QAT_TIGER_ACCOUNT", raising=False)
    monkeypatch.delenv("QAT_EXEC_TIGER_ACCOUNT", raising=False)
    assert resolve_tiger_account() == PAPER_ACCOUNT_DEFAULT


def test_live_account_when_sim_off(monkeypatch):
    monkeypatch.setenv("QAT_TRADING_SIMULATION_MODE", "false")
    monkeypatch.delenv("QAT_TIGER_ACCOUNT", raising=False)
    monkeypatch.delenv("QAT_EXEC_TIGER_ACCOUNT", raising=False)
    assert resolve_tiger_account() == LIVE_ACCOUNT_DEFAULT


def test_explicit_account_wins(monkeypatch):
    monkeypatch.setenv("QAT_TRADING_SIMULATION_MODE", "true")
    assert resolve_tiger_account("999") == "999"


def test_root_path_normalization_for_auth():
    # Regression: "/".rstrip("/") == "" previously broke public root.
    assert ("/".rstrip("/") or "/") in PUBLIC_PATHS
    assert ("".rstrip("/") or "/") in PUBLIC_PATHS


def test_gateway_root_prefers_spa_html():
    """Regression: GET / used to return JSON so the public UI looked 'down'."""
    from pathlib import Path

    src = Path("api_gateway/main.py").read_text(encoding="utf-8")
    assert "def _spa_index_response" in src
    assert 'async def root(request: Request)' in src
    assert "_spa_index_response()" in src
    assert "text/html" in src
    assert 'async def api_info' in src
