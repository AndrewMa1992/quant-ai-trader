"""shared/execution_mode.py – Single source of truth for paper vs live.

Paper/simulation is the default. Live trading requires an explicit
``QAT_EXECUTION_MODE=live`` AND ``QAT_TRADING_SIMULATION_MODE=false``.
"""

from __future__ import annotations

import os
from typing import Any


def is_simulation_mode() -> bool:
    """Return True when the system must stay in paper/sim mode."""
    raw = os.getenv("QAT_TRADING_SIMULATION_MODE", "true").strip().lower()
    return raw in ("1", "true", "yes", "on", "")


def get_execution_mode() -> str:
    """Return ``paper`` or ``live`` after applying the simulation lock."""
    if is_simulation_mode():
        return "paper"
    env_mode = os.getenv("QAT_EXECUTION_MODE", "").strip().lower()
    if env_mode:
        return "live" if env_mode == "live" else "paper"
    try:
        from configs.pipeline_config import pipeline_config

        mode = str(getattr(pipeline_config, "EXECUTION_MODE", "paper")).lower()
    except Exception:
        mode = "paper"
    return "live" if mode == "live" else "paper"


def is_live_execution() -> bool:
    """True only when live mode is explicitly enabled and sim lock is off."""
    return get_execution_mode() == "live"


def can_place_live_order(tiger_bridge: Any = None) -> bool:
    """True only when live mode is on and Tiger is connected."""
    if not is_live_execution():
        return False
    if tiger_bridge is None:
        return False
    try:
        return bool(tiger_bridge.is_connected())
    except Exception:
        return False
