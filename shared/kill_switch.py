"""shared/kill_switch.py – Durable portfolio kill switch (HF-style).

Once engaged, all new risk-taking is blocked until an explicit reset.
State persists under ``cache/kill_switch.json`` so restarts keep the halt.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

_DEFAULT_PATH = Path("cache/kill_switch.json")
_LOCK = threading.RLock()


class KillSwitch:
    """Process-wide durable kill switch."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else _DEFAULT_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._state: Dict[str, Any] = {
            "engaged": False,
            "reason": "",
            "engaged_at": None,
            "engaged_by": "",
            "reset_at": None,
            "reset_by": "",
        }
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._state.update(data)
        except Exception as exc:
            logger.warning(f"KillSwitch load failed: {exc}")

    def _save(self) -> None:
        try:
            self.path.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.error(f"KillSwitch save failed: {exc}")

    @property
    def engaged(self) -> bool:
        with _LOCK:
            return bool(self._state.get("engaged"))

    def status(self) -> Dict[str, Any]:
        with _LOCK:
            return dict(self._state)

    def engage(self, reason: str, engaged_by: str = "system") -> Dict[str, Any]:
        with _LOCK:
            self._state["engaged"] = True
            self._state["reason"] = reason
            self._state["engaged_at"] = datetime.now(timezone.utc).isoformat()
            self._state["engaged_by"] = engaged_by
            self._save()
            logger.error(f"🛑 KILL SWITCH ENGAGED by {engaged_by}: {reason}")
            return dict(self._state)

    def reset(self, reset_by: str = "operator") -> Dict[str, Any]:
        with _LOCK:
            self._state["engaged"] = False
            self._state["reason"] = ""
            self._state["reset_at"] = datetime.now(timezone.utc).isoformat()
            self._state["reset_by"] = reset_by
            self._save()
            logger.warning(f"🟢 KILL SWITCH RESET by {reset_by}")
            return dict(self._state)


_GLOBAL: Optional[KillSwitch] = None


def get_kill_switch() -> KillSwitch:
    global _GLOBAL
    if _GLOBAL is None:
        _GLOBAL = KillSwitch()
    return _GLOBAL
