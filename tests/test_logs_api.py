"""Tests for the read-only server logs API (gateway /api/v2/logs)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

import api_gateway.routes.logs as logs_mod


@pytest.fixture()
def logs(tmp_path, monkeypatch):
    monkeypatch.setattr(logs_mod, "logs_dir", lambda: tmp_path)
    (tmp_path / "execution.err.log").write_text(
    "\n".join(f"line {i}" for i in range(1, 501)) + "\n", encoding="utf-8"
    )
    (tmp_path / "cd-deploy.log").write_text("[ok] CD complete\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("not a log", encoding="utf-8")
    return tmp_path


def test_safe_log_path_ok(logs):
    p = logs_mod.safe_log_path("cd-deploy.log")
    assert p.name == "cd-deploy.log"


@pytest.mark.parametrize(
    "bad",
    ["../secrets.pem", "..%2Fx.log", "a/b.log", ".env", "key.pem", "x.log.exe", ""],
)
def test_safe_log_path_rejects(logs, bad):
    with pytest.raises(HTTPException) as exc:
        logs_mod.safe_log_path(bad)
    assert exc.value.status_code == 400


def test_safe_log_path_missing_file(logs):
    with pytest.raises(HTTPException) as exc:
        logs_mod.safe_log_path("missing.log")
    assert exc.value.status_code == 404


def test_tail_returns_last_lines(logs):
    out = logs_mod.tail_file(logs / "execution.err.log", lines=10)
    assert out["returned_lines"] == 10
    assert out["lines"][-1] == "line 500"
    assert out["lines"][0] == "line 491"


def test_tail_grep_filters(logs):
    out = logs_mod.tail_file(logs / "execution.err.log", lines=500, grep="LINE 42")
    assert all("line 42" in ln for ln in out["lines"])
    assert "line 420" in out["lines"]


@pytest.mark.asyncio
async def test_list_logs_excludes_non_logs(logs):
    resp = await logs_mod.list_logs()
    names = [f["name"] for f in resp.data["files"]]
    assert "execution.err.log" in names
    assert "cd-deploy.log" in names
    assert "notes.md" not in names


@pytest.mark.asyncio
async def test_read_log_endpoint(logs):
    resp = await logs_mod.read_log("cd-deploy.log", tail=50, grep=None)
    assert resp.success
    assert resp.data["lines"] == ["[ok] CD complete"]
