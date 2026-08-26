"""Tests for shared Tiger OpenAPI connection helpers (no live SDK)."""

from __future__ import annotations

from pathlib import Path

import pytest

import shared.tiger_sdk as ts


class _Settings:
    TIGER_ID = "20159337"
    TIGER_ACCOUNT = "21837535188693626"
    TIGER_LICENSE = ""
    TIGER_PRIVATE_KEY_PATH = "./certs/tiger_private_key.pem"
    TIGER_PRIVATE_KEY = ""
    TIGER_SANDBOX = False


def test_paper_does_not_force_sandbox(monkeypatch):
    monkeypatch.delenv("QAT_TIGER_SANDBOX", raising=False)
    monkeypatch.setenv("QAT_TIGER_PAPER_TRADING", "true")
    monkeypatch.setenv("QAT_TRADING_SIMULATION_MODE", "true")
    monkeypatch.setattr(ts, "get_settings", lambda: _Settings())
    assert ts.is_sandbox_requested() is False


def test_sandbox_opt_in(monkeypatch):
    monkeypatch.setenv("QAT_TIGER_SANDBOX", "true")
    monkeypatch.setattr(ts, "get_settings", lambda: _Settings())
    assert ts.is_sandbox_requested() is True


def test_license_defaults_include_tbsg(monkeypatch):
    monkeypatch.delenv("QAT_TIGER_LICENSE", raising=False)
    monkeypatch.setattr(ts, "get_settings", lambda: _Settings())
    cands = ts._license_candidates()
    assert cands[0] == "TBSG"
    assert "TBHK" in cands


def test_resolve_key_from_project_root(tmp_path, monkeypatch):
    certs = tmp_path / "certs"
    certs.mkdir()
    pem = certs / "tiger_private_key.pem"
    pem.write_text("-----BEGIN RSA PRIVATE KEY-----\n" + ("A" * 200) + "\n-----END RSA PRIVATE KEY-----\n")
    monkeypatch.setenv("QAT_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(ts, "get_settings", lambda: _Settings())
    got = ts.resolve_private_key_path()
    assert got == pem


def test_load_private_key_strips_pem(tmp_path, monkeypatch):
    certs = tmp_path / "certs"
    certs.mkdir()
    body = "B" * 200
    (certs / "tiger_private_key.pem").write_text(
        "-----BEGIN RSA PRIVATE KEY-----\n" + body + "\n-----END RSA PRIVATE KEY-----\n"
    )
    monkeypatch.setenv("QAT_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(ts, "get_settings", lambda: _Settings())
    key = ts.load_private_key()
    assert "BEGIN" not in key
    assert body in key


def test_connect_uses_production_for_paper(monkeypatch):
    captured: dict = {}

    class Cfg:
        def __init__(self, sandbox_debug=False, **kwargs):
            self.sandbox_debug = sandbox_debug
            self.private_key = None
            self.tiger_id = None
            self.account = None
            self.license = None

    class Trade:
        def __init__(self, cfg):
            captured["cfg"] = cfg

        def get_prime_assets(self, **kwargs):
            return {"cash": 1700}

    class Quote:
        def __init__(self, cfg):
            captured["quote"] = True

    monkeypatch.setattr(ts, "_try_import", lambda: (Cfg, Trade, Quote))
    monkeypatch.setattr(ts, "load_private_key", lambda: "KEY")
    monkeypatch.setattr(ts, "is_sandbox_requested", lambda: False)
    monkeypatch.setattr(ts, "get_settings", lambda: _Settings())
    monkeypatch.setattr(ts, "_props_candidates", lambda: [])
    ts.reset()
    trade, quote = ts.connect(force=True, account="21837535188693626")
    assert isinstance(trade, Trade)
    assert isinstance(quote, Quote)
    assert captured["cfg"].sandbox_debug is False
    assert captured["cfg"].account == "21837535188693626"
    assert captured["cfg"].license == "TBSG"
    ts.reset()


def test_connect_retries_license_on_auth_error(monkeypatch):
    attempts: list[str] = []

    class Cfg:
        def __init__(self, sandbox_debug=False, **kwargs):
            self.sandbox_debug = sandbox_debug
            self.private_key = self.tiger_id = self.account = self.license = None

    class Trade:
        def __init__(self, cfg):
            attempts.append(cfg.license)

        def get_prime_assets(self, **kwargs):
            if attempts[-1] == "TBSG":
                raise RuntimeError("invalid license")
            return {"ok": True}

    class Quote:
        def __init__(self, cfg):
            pass

    monkeypatch.setattr(ts, "_try_import", lambda: (Cfg, Trade, Quote))
    monkeypatch.setattr(ts, "load_private_key", lambda: "KEY")
    monkeypatch.setattr(ts, "is_sandbox_requested", lambda: False)
    monkeypatch.setattr(ts, "get_settings", lambda: _Settings())
    monkeypatch.setattr(ts, "_props_candidates", lambda: [])
    ts.reset()
    trade, _ = ts.connect(force=True, account="21837535188693626")
    assert attempts[0] == "TBSG"
    assert "TBHK" in attempts
    assert trade is not None
    ts.reset()


@pytest.mark.asyncio
async def test_broker_surfaces_sdk_error(monkeypatch):
    from services.execution_service.live.tiger_broker import TigerBroker

    def boom(**kwargs):
        raise RuntimeError("tigeropen not installed: missing")

    monkeypatch.setattr("shared.tiger_sdk.connect", boom)
    monkeypatch.setattr("shared.tiger_sdk.last_error", lambda: "tigeropen not installed: missing")
    broker = TigerBroker(account="21837535188693626", require_confirm=False)
    summary = await broker.get_account_summary()
    assert summary["error"] == "sdk_unavailable"
    assert "tigeropen" in (summary.get("detail") or "")
    assert summary["account"] == "21837535188693626"


def test_broker_does_not_flip_sandbox():
    src = Path("services/execution_service/live/tiger_broker.py").read_text(encoding="utf-8")
    assert "retrying sandbox" not in src
    assert "from shared.tiger_sdk import connect" in src
    assert "sdk_unavailable" in src
