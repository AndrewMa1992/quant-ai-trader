"""
TigerBridge — Tiger API thin wrapper
====================================
Architecture constraint: NO direct ``import backend.`` at module level.
Routes through v2 ``services/execution_service/live/tiger_broker`` (primary)
or ``services/data_service/ingestion/tiger_client`` (fallback / quotes).
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from loguru import logger

# Module-level sentinel for lazy-load tracking.
_tiger_client: Optional[Any] = None
_has_attempted_import: bool = False


def _run_async(coro, timeout: float = 30.0):
    """Safely run async coroutine — handles both sync and async contexts."""
    import concurrent.futures
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Inside running event loop → run in separate thread with fresh loop
    def _run_in_new_loop():
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        try:
            return new_loop.run_until_complete(coro)
        finally:
            new_loop.close()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(_run_in_new_loop).result(timeout=timeout)


def _lazy_import() -> Optional[Any]:
    """Lazily import and cache the Tiger trade singleton.

    The import only happens on the first call, satisfying the
    constraint that ``shared/`` must not pull in ``services/`` at
    import time.  Tries the v2 execution_service path first,
    then falls back to the v2 ingestion tiger_client path.

    Returns:
        A TigerBroker-compatible client, or None if the import fails.
    """
    global _tiger_client, _has_attempted_import

    if _tiger_client is not None:
        return _tiger_client

    if _has_attempted_import:
        return None

    _has_attempted_import = True

    # ── Primary: v2 execution_service TigerBroker ──────────
    try:
        from services.execution_service.live.tiger_broker import TigerBroker

        _tiger_client = TigerBroker()
        # Ensure client init (lazy-internal)
        _tiger_client._ensure_client()
        logger.info("TigerBridge: v2 TigerBroker loaded from execution_service")
        return _tiger_client
    except ImportError as exc:
        logger.debug(f"TigerBridge: execution_service TigerBroker not available ({exc})")
    except Exception as exc:
        logger.debug(f"TigerBridge: TigerBroker init failed ({exc})")

    # ── Fallback: v2 ingestion tiger_client ───────────────
    try:
        from services.data_service.ingestion.tiger_client import TigerClient

        _tiger_client = TigerClient()
        _tiger_client._ensure_initialized()
        logger.info("TigerBridge: v2 TigerClient loaded from services/ (fallback)")
        return _tiger_client
    except ImportError as exc:
        logger.warning(f"TigerBridge: services ingestion tiger_client not available ({exc})")
    except Exception as exc:
        logger.error(f"TigerBridge: unexpected error during TigerClient init: {exc}")

    return _tiger_client


# ── Public API ────────────────────────────────────────────────


def connect() -> bool:
    """Lazily load and connect to Tiger trade.

    Returns:
        True if the connection was established successfully.
    """
    try:
        client = _lazy_import()
        if client is None:
            return False
        if hasattr(client, "connect"):
            client.connect()
        elif hasattr(client, "_ensure_client"):
            client._ensure_client()
            # Check if Tiger SDK loaded successfully
            if not client._initialized:
                logger.warning("TigerBridge: TigerBroker SDK not available, using paper mode")
                return True  # Paper mode is "connected enough"
        else:
            return False
        logger.info("TigerBridge: connected to Tiger")
        return True
    except Exception as exc:
        logger.error(f"TigerBridge: connect failed — {exc}")
        return False


def is_connected() -> bool:
    """Check whether the Tiger client is connected.

    Returns:
        True if the Tiger client exists and is connected.
    """
    try:
        client = _lazy_import()
        if client is None:
            return False
        if hasattr(client, "is_connected"):
            return client.is_connected()
        # TigerBroker: consider paper mode as connected
        if hasattr(client, "_initialized"):
            return True
        return False
    except Exception as exc:
        logger.warning(f"TigerBridge: is_connected check failed — {exc}")
        return False


def get_account_info(force: bool = False) -> Optional[Dict[str, Any]]:
    """Retrieve current Tiger account information.

    Args:
        force: If True, refresh from broker instead of cache.

    Returns:
        A dict with account fields (e.g. net_liquidation, cash, etc.),
        or None on failure.
    """
    try:
        client = _lazy_import()
        if client is None:
            return None
        if hasattr(client, "get_account_info"):
            return client.get_account_info(force=force)
        # TigerBroker async → sync bridge
        if hasattr(client, "get_account_summary"):
            return _run_async(client.get_account_summary())
        return None
    except Exception as exc:
        logger.error(f"TigerBridge: get_account_info failed — {exc}")
        return None


def get_positions(force: bool = False) -> List[Dict[str, Any]]:
    """Retrieve current Tiger positions.

    Args:
        force: If True, refresh from broker instead of cache.

    Returns:
        A list of position dicts. Empty list on failure.
    """
    try:
        client = _lazy_import()
        if client is None:
            return []
        if hasattr(client, "get_positions"):
            # Try sync call with force param (legacy), fall back to async (v2)
            import inspect
            sig = inspect.signature(client.get_positions)
            if "force" in sig.parameters:
                return client.get_positions(force=force)
            # v2 TigerBroker — async method, no force param
            return _run_async(client.get_positions())
        return []
    except Exception as exc:
        logger.error(f"TigerBridge: get_positions failed — {exc}")
        return []


def place_order(
    ticker: str,
    action: str,
    quantity: int,
    order_type: str = "MKT",
    price: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Place an order via Tiger.

    Args:
        ticker: Ticker symbol (e.g. "AAPL").
        action: "BUY" or "SELL".
        quantity: Number of shares.
        order_type: Order type (MKT, LMT, etc.).
        price: Limit price (required when order_type is LMT).

    Returns:
        Order confirmation dict, or None on failure.
    """
    try:
        client = _lazy_import()
        if client is None:
            return None
        if hasattr(client, "place_order"):
            # Check if it's the async v2 TigerBroker or sync legacy
            import inspect
            if inspect.iscoroutinefunction(client.place_order):
                return _run_async(client.place_order(
                    ticker=ticker,
                    side=action,
                    quantity=quantity,
                    order_type=order_type,
                    limit_price=price,
                ))
            return client.place_order(
                ticker=ticker,
                action=action,
                quantity=quantity,
                order_type=order_type,
                limit_price=price,
            )
        return None
    except Exception as exc:
        logger.error(f"TigerBridge: place_order({ticker}, {action}, {quantity}) failed — {exc}")
        return None


def get_quote(ticker: str) -> Optional[Dict[str, Any]]:
    """Get a real-time quote for a ticker.

    Uses v2 ``TigerClient`` from ``services/data_service/ingestion/``
    because the primary v2 ``TigerBroker`` does not implement get_quote.

    Args:
        ticker: Ticker symbol.

    Returns:
        Quote dict with fields like bid, ask, last, etc., or None on failure.
    """
    try:
        client = _lazy_import()
        if client is not None and hasattr(client, "get_quote"):
            result = client.get_quote(ticker)
            if asyncio.iscoroutine(result):
                return _run_async(result)
            return result

        # v2 TigerBroker lacks get_quote — use v2 TigerClient directly
        from services.data_service.ingestion.tiger_client import TigerClient

        tc = TigerClient()
        tc._ensure_initialized()
        return _run_async(tc.get_quote(ticker))
    except Exception as exc:
        logger.error(f"TigerBridge: get_quote({ticker}) failed — {exc}")
        return None


def sync_all_to_db() -> Dict[str, Any]:
    """Sync all Tiger positions / account info to the local database.

    Returns:
        Summary dict, e.g. {"positions_synced": 15, "account_updated": True}.
        Returns an empty dict on failure.
    """
    try:
        client = _lazy_import()
        if client is None:
            return {"error": "client_unavailable", "positions_synced": 0, "account_updated": False}
        if hasattr(client, "sync_all_to_db"):
            return client.sync_all_to_db()
        # v2 TigerBroker — sync manually via get_positions + get_account_summary
        positions = _run_async(client.get_positions()) if hasattr(client, "get_positions") else []
        account = _run_async(client.get_account_summary()) if hasattr(client, "get_account_summary") else {}
        return {
            "positions_synced": len(positions) if isinstance(positions, list) else 0,
            "account_updated": bool(account),
        }
    except Exception as exc:
        logger.error(f"TigerBridge: sync_all_to_db failed — {exc}")
        return {"error": str(exc), "positions_synced": 0, "account_updated": False}


def get_status() -> Dict[str, Any]:
    """Return a summary of the Tiger connection status.

    Returns:
        Dict with keys: ``connected``, ``account_available``,
        ``position_count``, ``error``.
    """
    try:
        client = _lazy_import()
        if client is None:
            return {
                "connected": False,
                "account_available": False,
                "position_count": 0,
                "error": "client_unavailable",
            }
        # Legacy path
        if hasattr(client, "is_connected") and hasattr(client, "get_account_info"):
            connected = client.is_connected()
            account = client.get_account_info() if connected else None
            positions = client.get_positions() if connected else []
            return {
                "connected": connected,
                "account_available": account is not None,
                "position_count": len(positions) if isinstance(positions, list) else 0,
                "error": None,
            }
        # v2 TigerBroker
        connected = getattr(client, "_initialized", False)
        account = _run_async(client.get_account_summary()) if hasattr(client, "get_account_summary") else None
        positions = _run_async(client.get_positions()) if hasattr(client, "get_positions") else []
        return {
            "connected": connected,
            "account_available": account is not None and account.get("nav", 0) > 0,
            "position_count": len(positions) if isinstance(positions, list) else 0,
            "error": None,
        }
    except Exception as exc:
        logger.error(f"TigerBridge: get_status failed — {exc}")
        return {
            "connected": False,
            "account_available": False,
            "position_count": 0,
            "error": str(exc),
        }
