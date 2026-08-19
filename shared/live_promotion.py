"""shared/live_promotion.py – Paper → live promotion gate (HF-style).

Live trading is refused unless an explicit promotion record exists and
simulation mode is disabled. Prevents accidental live flips via env alone.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from loguru import logger

from shared.execution_mode import get_execution_mode, is_simulation_mode

_GATE_PATH = Path("cache/live_promotion.json")


def _load() -> Dict[str, Any]:
    if not _GATE_PATH.exists():
        return {"approved": False, "checklist": {}, "history": []}
    try:
        return json.loads(_GATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"approved": False, "checklist": {}, "history": []}


def _save(data: Dict[str, Any]) -> None:
    _GATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _GATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


REQUIRED_CHECKS = (
    "paper_soak_days",
    "risk_limits_loaded",
    "kill_switch_clear",
    "models_in_staging_or_prod",
    "operator_ack",
)


def evaluate_live_readiness(checklist: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Return readiness report without mutating gate state."""
    checklist = checklist or {}
    missing: List[str] = []
    for key in REQUIRED_CHECKS:
        if not checklist.get(key):
            missing.append(key)

    sim = is_simulation_mode()
    mode = get_execution_mode()
    ready = (not sim) and mode == "live" and not missing
    return {
        "ready": ready,
        "execution_mode": mode,
        "simulation_mode": sim,
        "missing": missing,
        "checklist": checklist,
    }


def can_place_live_orders() -> bool:
    """Hard gate used by TigerExecutor / liquidation."""
    if is_simulation_mode() or get_execution_mode() != "live":
        return False
    data = _load()
    return bool(data.get("approved"))


def approve_live(operator: str, checklist: Dict[str, Any]) -> Dict[str, Any]:
    """Approve live trading after checklist validation."""
    report = evaluate_live_readiness(checklist)
    if report["missing"]:
        raise ValueError(f"Live promotion incomplete: missing {report['missing']}")
    if is_simulation_mode():
        raise ValueError("Set QAT_TRADING_SIMULATION_MODE=false before live approval")

    data = _load()
    data["approved"] = True
    data["checklist"] = checklist
    data["approved_by"] = operator
    data["approved_at"] = datetime.now(timezone.utc).isoformat()
    hist = list(data.get("history") or [])
    hist.append({"action": "approve", "by": operator, "at": data["approved_at"]})
    data["history"] = hist[-50:]
    _save(data)
    logger.warning(f"LIVE PROMOTION APPROVED by {operator}")
    return data


def revoke_live(operator: str, reason: str = "") -> Dict[str, Any]:
    data = _load()
    data["approved"] = False
    data["revoked_by"] = operator
    data["revoked_at"] = datetime.now(timezone.utc).isoformat()
    data["revoke_reason"] = reason
    hist = list(data.get("history") or [])
    hist.append({"action": "revoke", "by": operator, "at": data["revoked_at"], "reason": reason})
    data["history"] = hist[-50:]
    _save(data)
    logger.warning(f"LIVE PROMOTION REVOKED by {operator}: {reason}")
    return data


def status() -> Dict[str, Any]:
    data = _load()
    return {
        "approved": bool(data.get("approved")),
        "can_place_live": can_place_live_orders(),
        "execution_mode": get_execution_mode(),
        "simulation_mode": is_simulation_mode(),
        "record": data,
    }
