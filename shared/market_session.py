"""
MarketSession — simple market-hours checker
============================================
Determines whether any major market is currently open for
live trading.  Used by the pipeline to skip trading cycles
outside market hours (P0-3).

Zero ``import backend.`` — uses a lightweight internal schedule.
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Dict

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
    },
}


def _is_market_open(market: str, now_utc: time) -> bool:
    """Check whether *market* is open at *now_utc*."""
    sched = _MARKETS.get(market)
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
        Dict like ``{"US": True, "HK": False, "CN": False}``.
    """
    now_utc = datetime.now(timezone.utc).time()
    status: Dict[str, bool] = {}
    for market in _MARKETS:
        status[market] = _is_market_open(market, now_utc)
    return status


def is_any_market_open() -> bool:
    """Check whether **any** major market is currently open.

    Returns:
        True if at least one tracked market is in session.
    """
    return any(get_market_status().values())


def is_market_open(market: str) -> bool:
    """Check whether a specific market is open.

    Args:
        market: Market code (``"US"``, ``"HK"``, ``"CN"``).

    Returns:
        True if the named market is in session.
    """
    now_utc = datetime.now(timezone.utc).time()
    return _is_market_open(market, now_utc)
