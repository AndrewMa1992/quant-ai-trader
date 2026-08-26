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
        or None on failure.  The ``nav`` field is also exposed as
        ``total_value`` for PortfolioManager compatibility.
    """
    try:
        client = _lazy_import()
        if client is None:
            return None
        if hasattr(client, "get_account_info"):
            return client.get_account_info(force=force)
        # TigerBroker async → sync bridge
        if hasattr(client, "get_account_summary"):
            result = _run_async(client.get_account_summary())
            if result and isinstance(result, dict):
                nav = (
                    result.get("nav")
                    or result.get("net_liquidation")
                    or result.get("total_value")
                    or 0.0
                )
                result["nav"] = nav
                result["total_value"] = result.get("total_value") or nav
                result.setdefault("buying_power", result.get("available_funds") or 0.0)
            return result
        return None
    except Exception as exc:
        logger.error(f"TigerBridge: get_account_info failed — {exc}")
        return None


def get_positions(force: bool = False) -> List[Dict[str, Any]]:
    """Retrieve current Tiger positions (normalized shares/quantity)."""
    try:
        client = _lazy_import()
        if client is None:
            return []
        raw: List[Dict[str, Any]] = []
        if hasattr(client, "get_positions"):
            import inspect
            sig = inspect.signature(client.get_positions)
            if "force" in sig.parameters:
                raw = client.get_positions(force=force) or []
            else:
                raw = _run_async(client.get_positions()) or []
        from shared.tiger_persist import normalize_position

        return [normalize_position(p if isinstance(p, dict) else dict(p)) for p in raw]
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


def _invoke(client: Any, name: str, *args: Any, **kwargs: Any) -> Any:
    """Call a sync or async client method by name."""
    import inspect

    fn = getattr(client, name, None)
    if not callable(fn):
        return None
    if inspect.iscoroutinefunction(fn):
        return _run_async(fn(*args, **kwargs))
    result = fn(*args, **kwargs)
    if asyncio.iscoroutine(result):
        return _run_async(result)
    return result


_LAST_SYNC: Dict[str, Any] = {"ts": 0.0, "snap": {}}
_SYNC_MIN_INTERVAL = 12.0


def sync_all_to_db(force: bool = False) -> Dict[str, Any]:
    """Sync Tiger positions / account / open+filled orders into local SQLite + Redis."""
    import time as _time

    now = _time.time()
    if not force and _LAST_SYNC["snap"] and (now - float(_LAST_SYNC["ts"] or 0)) < _SYNC_MIN_INTERVAL:
        return _LAST_SYNC["snap"]

    try:
        client = _lazy_import()
        if client is None:
            return {"error": "client_unavailable", "positions_synced": 0, "account_updated": False}
        if hasattr(client, "sync_all_to_db"):
            # Legacy path may already persist — also run our ORM writer for UI
            try:
                legacy = client.sync_all_to_db()
            except Exception as exc:
                logger.warning(f"legacy sync_all_to_db: {exc}")
                legacy = {}
        else:
            legacy = {}

        positions = get_positions(force=True)
        account = get_account_info(force=True) or {}

        open_orders: List[Dict[str, Any]] = []
        filled_orders: List[Dict[str, Any]] = []
        try:
            oo = _invoke(client, "get_open_orders")
            if isinstance(oo, list):
                open_orders = oo
        except Exception as exc:
            logger.debug(f"get_open_orders skipped: {exc}")
        try:
            fo = _invoke(client, "get_filled_orders")
            if isinstance(fo, list):
                filled_orders = fo
            else:
                hist = _invoke(client, "get_order_history")
                if isinstance(hist, list):
                    filled_orders = hist
        except Exception as exc:
            logger.debug(f"get_filled_orders skipped: {exc}")

        if not open_orders and getattr(client, "_client", None) is not None:
            try:
                from shared.tiger_assets import parse_order

                raw = client._client.get_open_orders()
                for o in raw or []:
                    open_orders.append(parse_order(o))
            except Exception as exc:
                logger.debug(f"raw get_open_orders skipped: {exc}")

        from shared.tiger_assets import merge_orders
        from shared.tiger_account import should_use_paper_account
        from shared.tiger_persist import load_positions_for_api, persist_tiger_snapshot

        all_orders = merge_orders(open_orders, filled_orders)

        nav = float(
            account.get("nav")
            or account.get("net_liquidation")
            or account.get("total_value")
            or 0.0
        )
        cash = float(account.get("cash") or 0.0)
        bp = float(account.get("buying_power") or account.get("available_funds") or 0.0)
        tiger_empty = nav <= 1.0 and cash <= 1.0 and bp <= 1.0 and not positions

        if tiger_empty and should_use_paper_account():
            existing = load_positions_for_api()
            existing_summary = existing.get("summary") or {}
            existing_nav = float(existing_summary.get("total_market_value") or 0.0)
            existing_cash = float(existing_summary.get("cash") or 0.0)
            existing_pos = existing.get("positions") or []
            if existing_nav > 1.0 or existing_cash > 1.0 or existing_pos:
                logger.warning(
                    "Tiger paper empty (cash=%.2f nav=%.2f bp=%.2f) — "
                    "keeping DB snapshot cash=%.2f nav=%.2f; still writing orders",
                    cash, nav, bp, existing_cash, existing_nav,
                )
                keep_pos = [
                    {
                        "ticker": p.get("ticker"),
                        "shares": p.get("quantity") or p.get("shares"),
                        "avg_cost": p.get("cost_basis") or p.get("avg_cost"),
                        "market_value": p.get("market_value"),
                        "market_price": p.get("market_price"),
                    }
                    for p in existing_pos
                ]
                keep_acct = {
                    "nav": existing_nav,
                    "cash": existing_cash,
                    "total_value": existing_nav,
                    "buying_power": existing_summary.get("buying_power") or existing_cash,
                    "source": "tiger_zero_nav_preserved",
                    "account": account.get("account"),
                }
                snap = persist_tiger_snapshot(keep_pos, keep_acct, all_orders)
                snap["skipped_empty_overwrite"] = True
                snap["tiger_cash"] = cash
                snap["tiger_nav"] = nav
                if isinstance(legacy, dict) and legacy:
                    snap["legacy"] = legacy
                _LAST_SYNC["ts"] = now
                _LAST_SYNC["snap"] = snap
                return snap

        snap = persist_tiger_snapshot(positions, account, all_orders)
        if isinstance(legacy, dict) and legacy:
            snap["legacy"] = legacy
        _LAST_SYNC["ts"] = now
        _LAST_SYNC["snap"] = snap
        return snap
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
        nav = 0.0
        if isinstance(account, dict):
            nav = float(account.get("nav") or account.get("net_liquidation") or account.get("cash") or 0)
        return {
            "connected": connected,
            "account_available": account is not None and nav > 0,
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
