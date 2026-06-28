"""
MarketSession — simple market-hours checker
============================================
Determines whether any major market is currently open for
live trading.  Used by the pipeline to skip trading cycles
outside market hours (P0-3).

Zero ``import backend.`` — uses a lightweight internal schedule.
"""

from __future__ import annotations

import os
from datetime import datetime, time, timezone
from typing import Dict, List

from loguru import logger

# ── Market schedules (UTC) ───────────────────────────────────
# Times are in UTC.  These are the core sessions; pre/post-market
# is NOT considered "open" for the main trading pipeline.
_MARKETS: Dict[str, Dict[str, time]] = {
    "US": {
        "open": time(14, 30),  # 09:30 EST → 14:30 UTC (winter)
        "close": time(21, 0),  # 16:00 EST → 21:00 UTC (winter)
    },
    "HK": {
        "open": time(1, 30),   # 09:30 HKT → 01:30 UTC
        "close": time(8, 0),   # 16:00 HKT → 08:00 UTC
    },
    "CN": {
        "open": time(1, 30),   # 09:30 CST → 01:30 UTC
        "close": time(7, 0),   # 15:00 CST → 07:00 UTC
        # Lunch break 11:30-13:00 CST (03:30-05:00 UTC) is treated as tradable
    },
    "SG": {
        "open": time(1, 0),    # 09:00 SGT → 01:00 UTC
        "close": time(9, 0),   # 17:00 SGT → 09:00 UTC
    },
    "AU": {
        "open": time(0, 0),    # 10:00 AEST → 00:00 UTC (winter)
        "close": time(6, 0),   # 16:00 AEST → 06:00 UTC (winter)
    },
    "NZ": {
        "open": time(22, 0),   # 10:00 NZST → 22:00 UTC (winter, prev day)
        "close": time(4, 45),  # 16:45 NZST → 04:45 UTC (winter)
    },
}

# ── US Extended Hours (UTC) ───────────────────────────────────
_EXTENDED_HOURS: Dict[str, Dict[str, time]] = {
    "US_pre": {
        "open": time(9, 0),    # 04:00 EST → 09:00 UTC
        "close": time(14, 30), # 09:30 EST → 14:30 UTC
    },
    "US_post": {
        "open": time(21, 0),   # 16:00 EST → 21:00 UTC
        "close": time(1, 0),   # 20:00 EST → 01:00 UTC next day
    },
}

# ── Trading hours mode ───────────────────────────────────────
TRADABLE_HOURS: str = os.getenv("QAT_MARKET_HOURS_MODE", "extended")
# Valid modes: "regular", "extended", "all"


def _is_weekday() -> bool:
    """Check if today is a weekday (Mon-Fri)."""
    return datetime.now(timezone.utc).weekday() < 5


def _is_market_open(market: str, now_utc: time) -> bool:
    """Check whether *market* is open at *now_utc*."""
    if not _is_weekday():
        return False
    sched = _MARKETS.get(market)
    if sched is None:
        return False
    open_t = sched["open"]
    close_t = sched["close"]
    if open_t <= close_t:
        return open_t <= now_utc < close_t
    # Overnight session (e.g. spanning midnight).
    return now_utc >= open_t or now_utc < close_t


def _is_extended_open(session_key: str, now_utc: time) -> bool:
    """Check whether an extended-hours session is active."""
    if not _is_weekday():
        return False
    sched = _EXTENDED_HOURS.get(session_key)
    if sched is None:
        return False
    open_t = sched["open"]
    close_t = sched["close"]
    if open_t <= close_t:
        return open_t <= now_utc < close_t
    # Overnight session (e.g. spanning midnight).
    return now_utc >= open_t or now_utc < close_t


def get_market_status() -> Dict[str, bool]:
    """Return open/closed status for all tracked markets.

    Returns:
        Dict like ``{"US": True, "HK": False, "CN": False, ...}``.
    """
    now_utc = datetime.now(timezone.utc).time()
    status: Dict[str, bool] = {}
    for market in _MARKETS:
        status[market] = _is_market_open(market, now_utc)
    return status


def is_any_market_open() -> bool:
    """Check whether **any** major market is currently open (regular hours only).

    Returns:
        True if at least one tracked market is in its regular session.
    """
    return any(get_market_status().values())


def is_market_open(market: str) -> bool:
    """Check whether a specific market is open.

    Args:
        market: Market code (``"US"``, ``"HK"``, ``"CN"``, ``"SG"``, ``"AU"``, ``"NZ"``).

    Returns:
        True if the named market is in session.
    """
    now_utc = datetime.now(timezone.utc).time()
    return _is_market_open(market, now_utc)


# ── Extended Hours Functions ──────────────────────────────────

def is_pre_market_us() -> bool:
    """Check whether US pre-market (04:00-09:30 EST) is active."""
    now_utc = datetime.now(timezone.utc).time()
    return _is_extended_open("US_pre", now_utc)


def is_post_market_us() -> bool:
    """Check whether US post-market (16:00-20:00 EST) is active."""
    now_utc = datetime.now(timezone.utc).time()
    return _is_extended_open("US_post", now_utc)


def is_extended_hours() -> bool:
    """Check whether any extended-hours session is currently active.

    Returns:
        True if US pre-market or post-market is in session.
    """
    return is_pre_market_us() or is_post_market_us()


def get_active_markets_extended() -> List[str]:
    """Return list of all markets currently tradable (regular + extended).

    Returns:
        List of market codes that are in regular session, plus ``"US"``
        during extended hours.
    """
    active = [m for m, v in get_market_status().items() if v]
    if (is_pre_market_us() or is_post_market_us()) and "US" not in active:
        active.append("US")
    return active


def is_any_market_tradable() -> bool:
    """Check whether **any** market is currently tradable.

    Respects ``TRADABLE_HOURS`` / ``QAT_MARKET_HOURS_MODE`` env var:

    - ``"regular"``: regular hours only (same as ``is_any_market_open``)
    - ``"extended"``: regular + US pre/post market (default)
    - ``"all"``: regular + extended

    Returns:
        True if at least one market is in a tradable session.
    """
    if TRADABLE_HOURS == "regular":
        return is_any_market_open()
    # "extended" or "all" — include US pre/post market
    return is_any_market_open() or is_extended_hours()
