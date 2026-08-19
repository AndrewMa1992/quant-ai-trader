"""
MarketSession — market-hours checker
============================================
Determines whether markets are open for live trading.
Pipeline can skip cycles when TRADING_HOURS_ONLY and none are open.

US can run 24h (incl. weekends) when QAT_US_24H_TRADING=true (default).
"""

from __future__ import annotations

import os
from datetime import datetime, time, timezone
from typing import Dict

# ── Market schedules (UTC) ───────────────────────────────────
# Core regular sessions. US 24h mode bypasses this schedule.
_MARKETS: Dict[str, Dict[str, time]] = {
    "US": {
        "open": time(14, 30),  # 09:30 EST → 14:30 UTC (winter approx)
        "close": time(21, 0),  # 16:00 EST → 21:00 UTC
    },
    "HK": {
        "open": time(1, 30),   # 09:30 HKT
        "close": time(8, 0),   # 16:00 HKT
    },
    "SG": {
        "open": time(1, 0),    # 09:00 SGT
        "close": time(9, 0),   # 17:00 SGT
    },
    "AU": {
        "open": time(0, 0),    # 10:00 AEST ≈ 00:00 UTC (approx; ignores DST)
        "close": time(6, 0),   # 16:00 AEST
    },
    "NZ": {
        "open": time(22, 0),   # 10:00 NZST → prev day 22:00 UTC (winter approx)
        "close": time(4, 45),  # 16:45 NZST → 04:45 UTC (overnight span)
    },
}


def _us_24h_enabled() -> bool:
    raw = os.getenv("QAT_US_24H_TRADING", "true").strip().lower()
    return raw in ("1", "true", "yes", "on", "")


def _is_weekday() -> bool:
    return datetime.now(timezone.utc).weekday() < 5


def _is_market_open(market: str, now_utc: time) -> bool:
    """Check whether *market* is open at *now_utc*."""
    mkt = market.upper()
    if mkt == "US" and _us_24h_enabled():
        return True
    if not _is_weekday():
        return False
    sched = _MARKETS.get(mkt)
    if sched is None:
        return False
    open_t = sched["open"]
    close_t = sched["close"]
    if open_t <= close_t:
        return open_t <= now_utc < close_t
    # Overnight session (e.g. NZ spanning midnight).
    return now_utc >= open_t or now_utc < close_t


def get_market_status() -> Dict[str, bool]:
    """Return open/closed status for all tracked markets."""
    now_utc = datetime.now(timezone.utc).time()
    status: Dict[str, bool] = {}
    for market in _MARKETS:
        status[market] = _is_market_open(market, now_utc)
    return status


def is_any_market_open() -> bool:
    """True if at least one tracked market is in session (or US 24h)."""
    return any(get_market_status().values())


def is_market_open(market: str) -> bool:
    """True if the named market is in session."""
    now_utc = datetime.now(timezone.utc).time()
    return _is_market_open(market, now_utc)
