"""
TigerBridge — Tiger API thin wrapper
====================================
Architecture constraint: NO direct ``import backend.`` at module level.
Uses lazy import to satisfy the "clean 3 references" requirement.

Provides a unified interface to Tiger trade for the shared/ layer,
delegating to ``backend.data_engine.tiger_client`` at runtime.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loguru import logger

# Module-level sentinel for lazy-load tracking.
_tiger_client: Optional[Any] = None
_has_attempted_import: bool = False


def _lazy_import() -> Optional[Any]:
    """Lazily import and cache the Tiger trade singleton.

    The import only happens on the first call, satisfying the
    constraint that ``shared/`` must not pull in ``backend/`` at
    import time.

    Returns:
        The TigerTrade singleton, or None if the import fails.
    """
    global _tiger_client, _has_attempted_import

    if _tiger_client is not None:
        return _tiger_client

    if _has_attempted_import:
        return None

    _has_attempted_import = True
    try:
        from backend.data_engine.tiger_client import tiger_client  # type: ignore[import-untyped]

        _tiger_client = tiger_client
        logger.info("TigerBridge: TigerTrade singleton loaded")
    except ImportError as exc:
        logger.warning(f"TigerBridge: backend.data_engine.tiger_client not available ({exc})")
    except Exception as exc:
        logger.error(f"TigerBridge: unexpected error during lazy import: {exc}")

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
        client.connect()
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
        return client.is_connected
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
        return client.get_account_info(force=force)
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
        return client.get_positions(force=force)
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
        return client.place_order(
            ticker=ticker,
            action=action,
            quantity=quantity,
            order_type=order_type,
            price=price,
        )
    except Exception as exc:
        logger.error(f"TigerBridge: place_order({ticker}, {action}, {quantity}) failed — {exc}")
        return None


def get_quote(ticker: str) -> Optional[Dict[str, Any]]:
    """Get a real-time quote for a ticker.

    Args:
        ticker: Ticker symbol.

    Returns:
        Quote dict with fields like bid, ask, last, etc., or None on failure.
    """
    try:
        client = _lazy_import()
        if client is None:
            return None
        return client.get_quote(ticker)
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
        return client.sync_all_to_db()
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
        connected = client.is_connected if hasattr(client, "is_connected") else False
        account = client.get_account_info() if connected and hasattr(client, "get_account_info") else None
        positions = client.get_positions() if connected and hasattr(client, "get_positions") else []
        return {
            "connected": connected,
            "account_available": account is not None,
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
