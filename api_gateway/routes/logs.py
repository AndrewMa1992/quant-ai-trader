"""api_gateway/routes/logs.py – Read-only server log access over HTTP.

Exposes the files in ``settings.LOGS_DIR`` (service out/err logs, CD deploy
log, watchdog logs, pipeline logs) so the web UI and remote agents can
inspect them without RDP access to the Windows box.

GET /api/v2/logs                  → list log files (name, size, mtime)
GET /api/v2/logs/{name}?tail=200  → last N lines (optional ?grep= filter)

Protected by the standard X-API-Key middleware (path starts with /api).
Only plain-text log files inside the logs directory are served.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from configs.settings import settings
from shared.schema import APIResponse

router = APIRouter()

# Log file names: conservative charset, .log/.txt only, no separators.
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.(log|txt)$")

MAX_TAIL_LINES = 5000
_READ_CHUNK = 64 * 1024
_MAX_BYTES = 2 * 1024 * 1024  # never return more than 2 MB per request


def logs_dir() -> Path:
    return Path(settings.LOGS_DIR)


def safe_log_path(name: str) -> Path:
    """Resolve a log file name inside the logs dir, rejecting traversal."""
    if not _NAME_RE.match(name or ""):
        raise HTTPException(status_code=400, detail=f"Invalid log name: {name!r}")
    base = logs_dir().resolve()
    path = (base / name).resolve()
    if path.parent != base:
        raise HTTPException(status_code=400, detail="Log path escapes logs directory")
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Log not found: {name}")
    return path


def tail_file(path: Path, lines: int, grep: Optional[str] = None) -> dict[str, Any]:
    """Return the last ``lines`` lines of ``path`` (reads from the end)."""
    lines = max(1, min(int(lines), MAX_TAIL_LINES))
    size = path.stat().st_size
    chunks: list[bytes] = []
    read = 0
    with path.open("rb") as f:
        pos = size
        while pos > 0 and read < _MAX_BYTES:
            step = min(_READ_CHUNK, pos)
            pos -= step
            f.seek(pos)
            chunk = f.read(step)
            chunks.append(chunk)
            read += step
            if b"".join(reversed(chunks)).count(b"\n") > lines:
                break
    data = b"".join(reversed(chunks))
    text = data.decode("utf-8", errors="replace")
    all_lines = text.splitlines()
    truncated = read < size
    if truncated and all_lines:
        # First line may start mid-way through a longer line — drop it.
        all_lines = all_lines[1:]
    out = all_lines[-lines:]
    if grep:
        needle = grep.lower()
        out = [ln for ln in out if needle in ln.lower()]
    return {
        "name": path.name,
        "size_bytes": size,
        "modified_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
        "requested_lines": lines,
        "returned_lines": len(out),
        "grep": grep or None,
        "truncated_head": truncated,
        "lines": out,
    }


@router.get("/logs", tags=["Logs"])
async def list_logs() -> APIResponse:
    """List server log files, newest first."""
    base = logs_dir()
    files: list[dict[str, Any]] = []
    if base.is_dir():
        for p in base.iterdir():
            if not p.is_file() or not _NAME_RE.match(p.name):
                continue
            st = p.stat()
            files.append({
                "name": p.name,
                "size_bytes": st.st_size,
                "modified_at": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            })
    files.sort(key=lambda f: f["modified_at"], reverse=True)
    return APIResponse(
        success=True,
        message=f"{len(files)} log files",
        data={"dir": str(base), "files": files},
    )


@router.get("/logs/{name}", tags=["Logs"])
async def read_log(
    name: str,
    tail: int = Query(default=200, ge=1, le=MAX_TAIL_LINES),
    grep: Optional[str] = Query(default=None, max_length=200),
) -> APIResponse:
    """Tail one log file. ``?grep=`` keeps only matching lines (case-insensitive)."""
    path = safe_log_path(name)
    payload = tail_file(path, tail, grep)
    return APIResponse(
        success=True,
        message=f"{payload['returned_lines']} lines from {name}",
        data=payload,
    )
