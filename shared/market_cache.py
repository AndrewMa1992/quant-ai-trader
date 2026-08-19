"""Redis-backed market/trading cache for the live pipeline.

Uses shared.redis_client (degrades to memory if Redis is down).
Always keeps a process-local L1 dict so sync callers work even when
async Redis client is degraded across thread boundaries.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from loguru import logger

# Process-local L1 (survives Redis thread/event-loop quirks)
_L1: Dict[str, Any] = {}


def _run(coro):
    """Run async redis helpers from sync pipeline code safely."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result(timeout=5)
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


async def _redis():
    from shared.redis_client import get_redis

    r = await get_redis()
    await r.connect()
    return r


async def cache_quote(ticker: str, price: float, extra: Optional[dict] = None, ttl: int = 30) -> None:
    payload = {"ticker": ticker, "price": float(price), **(extra or {})}
    _L1[f"qat:quote:{ticker}"] = payload
    r = await _redis()
    await r.cache_set(f"qat:quote:{ticker}", payload, ttl=ttl)


async def get_cached_quote(ticker: str) -> Optional[float]:
    local = _L1.get(f"qat:quote:{ticker}")
    if isinstance(local, dict) and local.get("price"):
        return float(local["price"])
    r = await _redis()
    data = await r.cache_get(f"qat:quote:{ticker}")
    if isinstance(data, dict) and data.get("price"):
        return float(data["price"])
    return None


async def cache_signals(signals: List[Dict[str, Any]], ttl: int = 600) -> None:
    _L1["qat:signals:latest"] = signals
    r = await _redis()
    await r.cache_set("qat:signals:latest", signals, ttl=ttl)
    try:
        await r.publish("qat:signals", {"count": len(signals), "signals": signals[:20]})
    except Exception:
        pass


async def cache_cycle_summary(summary: Dict[str, Any], ttl: int = 3600) -> None:
    _L1["qat:cycle:last"] = summary
    r = await _redis()
    await r.cache_set("qat:cycle:last", summary, ttl=ttl)
    try:
        await r.stream_add("qat:cycle_stream", summary, max_len=5000)
    except Exception:
        pass


async def cache_portfolio_snap(snap: Dict[str, Any], ttl: int = 120) -> None:
    _L1["qat:portfolio:snap"] = snap
    r = await _redis()
    await r.cache_set("qat:portfolio:snap", snap, ttl=ttl)


def sync_cache_quote(ticker: str, price: float, **extra: Any) -> None:
    _L1[f"qat:quote:{ticker}"] = {"ticker": ticker, "price": float(price), **extra}
    try:
        _run(cache_quote(ticker, price, extra or None))
    except Exception as exc:
        logger.debug(f"redis quote cache skip: {exc}")


def sync_get_quote(ticker: str) -> Optional[float]:
    local = _L1.get(f"qat:quote:{ticker}")
    if isinstance(local, dict) and local.get("price"):
        return float(local["price"])
    try:
        return _run(get_cached_quote(ticker))
    except Exception:
        return None


def sync_cache_signals(signals: List[Dict[str, Any]]) -> None:
    _L1["qat:signals:latest"] = signals
    try:
        _run(cache_signals(signals))
    except Exception as exc:
        logger.debug(f"redis signals cache skip: {exc}")


def sync_cache_cycle(summary: Dict[str, Any]) -> None:
    _L1["qat:cycle:last"] = summary
    try:
        _run(cache_cycle_summary(summary))
    except Exception as exc:
        logger.debug(f"redis cycle cache skip: {exc}")


def sync_cache_portfolio(snap: Dict[str, Any]) -> None:
    _L1["qat:portfolio:snap"] = snap
    try:
        _run(cache_portfolio_snap(snap))
    except Exception as exc:
        logger.debug(f"redis portfolio cache skip: {exc}")
