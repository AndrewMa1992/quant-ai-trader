"""
MarketSession — exchange-aware hours (DST via zoneinfo)
=======================================================
US can run 24h when QAT_US_24H_TRADING=true (default for paper).
HK/SG/AU/NZ use local exchange calendars (weekdays; lunch ignored for simplicity).
"""

from __future__ import annotations

import os
from datetime import datetime, time, timezone
from typing import Dict, Optional
from zoneinfo import ZoneInfo

# Local open/close (exchange local time). Lunch breaks ignored.
_MARKETS: Dict[str, Dict[str, object]] = {
    "US": {
        "tz": ZoneInfo("America/New_York"),
        "open": time(9, 30),
        "close": time(16, 0),
    },
    "HK": {
        "tz": ZoneInfo("Asia/Hong_Kong"),
        "open": time(9, 30),
        "close": time(16, 0),
    },
    "SG": {
        "tz": ZoneInfo("Asia/Singapore"),
        "open": time(9, 0),
        "close": time(17, 0),
    },
    "AU": {
        "tz": ZoneInfo("Australia/Sydney"),
        "open": time(10, 0),
        "close": time(16, 0),
    },
    "NZ": {
        "tz": ZoneInfo("Pacific/Auckland"),
        "open": time(10, 0),
        "close": time(16, 45),
    },
}


def _us_24h_enabled() -> bool:
    raw = os.getenv("QAT_US_24H_TRADING", "true").strip().lower()
    return raw in ("1", "true", "yes", "on", "")


def _is_weekday_local(now_local: datetime) -> bool:
    return now_local.weekday() < 5


def _is_market_open(market: str, now_utc: Optional[datetime] = None) -> bool:
    mkt = market.upper()
    if mkt == "US" and _us_24h_enabled():
        return True
    sched = _MARKETS.get(mkt)
    if sched is None:
        return False
    now_utc = now_utc or datetime.now(timezone.utc)
    now_local = now_utc.astimezone(sched["tz"])  # type: ignore[arg-type]
    if not _is_weekday_local(now_local):
        return False
    open_t: time = sched["open"]  # type: ignore[assignment]
    close_t: time = sched["close"]  # type: ignore[assignment]
    t = now_local.time()
    return open_t <= t < close_t


def get_market_status() -> Dict[str, bool]:
    now_utc = datetime.now(timezone.utc)
    return {market: _is_market_open(market, now_utc) for market in _MARKETS}


def is_any_market_open() -> bool:
    return any(get_market_status().values())


def is_market_open(market: str) -> bool:
    return _is_market_open(market)


def next_open_markets(rotation: list[str]) -> list[str]:
    """Return markets from rotation that are currently open (US 24h always)."""
    return [m for m in rotation if is_market_open(m)]
