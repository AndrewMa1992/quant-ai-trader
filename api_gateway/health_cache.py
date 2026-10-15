"""Short-lived cache for the aggregated /health payload.

Probing the database, Redis, and every microservice on each poll is the
expensive part of the gateway. A few seconds of reuse keeps the UI and
load balancers from fanning that work out continuously. /health/live stays
uncached.
"""

from __future__ import annotations

import time
from typing import TypeVar

T = TypeVar("T")

_cached_at: float | None = None
_cached_payload: object | None = None
TTL_SECONDS = 3.0


def read_health_cache(now: float | None = None) -> object | None:
    """Return the cached payload while it is younger than TTL_SECONDS."""
    if _cached_at is None or _cached_payload is None:
        return None
    current = time.time() if now is None else now
    if current - _cached_at >= TTL_SECONDS:
        return None
    return _cached_payload


def write_health_cache(payload: T, now: float | None = None) -> T:
    """Store a payload and return it."""
    global _cached_at, _cached_payload
    _cached_at = time.time() if now is None else now
    _cached_payload = payload
    return payload


def clear_health_cache() -> None:
    """Drop the cache. Tests use this so cases do not leak into each other."""
    global _cached_at, _cached_payload
    _cached_at = None
    _cached_payload = None
