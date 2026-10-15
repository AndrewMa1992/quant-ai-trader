"""Build and submit Tiger OpenAPI stock orders that actually reach the app.

``TradeClient.place_order()`` requires an ``Order`` object. The v2 broker used
to call it with ``contract=None`` kwargs, so nothing appeared on the Tiger
paper/demo book.

US paper/demo must use **limit** orders with ``outside_rth=True`` and, when
the SDK supports it, ``TradingSessionType.FULL``. Market orders are regular-
hours only and are dropped overnight / pre-market / after-hours.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_FILL_OFFSET = 0.0015  # 15 bps toward fill so paper orders execute in thin sessions


def market_for_ticker(ticker: str) -> str:
    t = (ticker or "").strip().upper()
    if t.endswith(".HK") or (t.isdigit() and len(t) <= 5):
        return "HK"
    if t.endswith(".SI"):
        return "SG"
    if t.endswith(".AU"):
        return "AU"
    if t.endswith(".NZ"):
        return "NZ"
    return "US"


def symbol_for_ticker(ticker: str) -> str:
    t = (ticker or "").strip().upper()
    if t.endswith(".HK"):
        return t[:-3].zfill(5)
    if t.endswith(".SI"):
        return t[:-3]
    if t.endswith(".AU") or t.endswith(".NZ"):
        return t[:-3]
    if t.isdigit() and len(t) <= 5:
        return t.zfill(5)
    return t


def currency_for_market(market: str) -> str:
    return {
        "US": "USD",
        "HK": "HKD",
        "SG": "SGD",
        "AU": "AUD",
        "NZ": "NZD",
    }.get((market or "US").upper(), "USD")


def tick_size(ticker: str, price: float) -> float:
    market = market_for_ticker(ticker)
    if market == "HK":
        if price < 0.25:
            return 0.001
        if price < 0.50:
            return 0.005
        if price < 10:
            return 0.01
        if price < 20:
            return 0.02
        if price < 100:
            return 0.05
        if price < 200:
            return 0.10
        if price < 500:
            return 0.20
        if price < 1000:
            return 0.50
        if price < 2000:
            return 1.00
        if price < 5000:
            return 2.00
        return 5.00
    if market == "SG":
        if price < 1.0:
            return 0.001
        if price < 10.0:
            return 0.005
        return 0.01
    if price >= 1.0:
        return 0.01
    return 0.0001


def align_tick(price: float, ticker: str) -> float:
    if price <= 0:
        return price
    size = tick_size(ticker, price)
    decimals = len(str(size).rstrip("0").split(".")[-1]) if "." in str(size) else 0
    aligned = round(round(price / size) * size, decimals or 2)
    return aligned if aligned > 0 else size


def _first_price(obj: Any) -> Optional[float]:
    if obj is None:
        return None
    if isinstance(obj, (int, float)) and not isinstance(obj, bool):
        val = float(obj)
        return val if val > 0 else None
    if isinstance(obj, dict):
        for key in (
            "latest_price",
            "last_price",
            "last",
            "price",
            "close",
            "pre_close",
            "ask_price",
            "bid_price",
        ):
            got = _first_price(obj.get(key))
            if got:
                return got
        return None
    for key in (
        "latest_price",
        "last_price",
        "last",
        "price",
        "close",
        "pre_close",
        "ask_price",
        "bid_price",
    ):
        if hasattr(obj, key):
            got = _first_price(getattr(obj, key, None))
            if got:
                return got
    return None


def quote_last_price(quote_client: Any, ticker: str) -> Optional[float]:
    """Best-effort last price from QuoteClient (SDK method names vary)."""
    if quote_client is None:
        return None
    symbol = symbol_for_ticker(ticker)
    for name in ("get_stock_briefs", "get_briefs", "get_realtime_quote", "get_stock_brief"):
        fn = getattr(quote_client, name, None)
        if not callable(fn):
            continue
        raw = None
        for args in (([symbol],), (symbol,), ([ticker],), (ticker,)):
            try:
                raw = fn(*args)
                break
            except TypeError:
                continue
            except Exception as exc:
                logger.debug("quote %s%s failed: %s", name, args, exc)
                raw = None
                break
        if raw is None:
            continue
        rows = raw if isinstance(raw, (list, tuple)) else [raw]
        for row in rows:
            px = _first_price(row)
            if px:
                return px
    return None


def aggressive_limit(side: str, last: float, ticker: str) -> float:
    """Nudge the limit toward a fill so paper/demo orders execute."""
    adj = 1.0 + _FILL_OFFSET if str(side).upper() == "BUY" else 1.0 - _FILL_OFFSET
    return align_tick(last * adj, ticker)


def _import_order_tools() -> tuple[Any, Any, Any]:
    from tigeropen.common.util.contract_utils import stock_contract
    from tigeropen.common.util.order_utils import limit_order, market_order

    return stock_contract, limit_order, market_order


def _apply_us_session(order: Any) -> None:
    """Allow pre-market, after-hours, and overnight on US paper/demo."""
    try:
        order.outside_rth = True
    except Exception:
        pass
    try:
        from tigeropen.common.consts import TradingSessionType

        full = getattr(TradingSessionType, "FULL", None)
        if full is not None:
            order.trading_session_type = full
    except Exception:
        logger.debug("TradingSessionType.FULL not available", exc_info=True)


def build_stock_order(
    *,
    account: str,
    ticker: str,
    side: str,
    quantity: int,
    order_type: str = "MKT",
    limit_price: float | None = None,
    quote_client: Any = None,
    paper: bool = True,
) -> Any:
    """Return a tigeropen ``Order`` ready for ``TradeClient.place_order``."""
    stock_contract, limit_order, market_order = _import_order_tools()
    qty = int(quantity)
    if qty <= 0:
        raise ValueError(f"quantity must be > 0, got {quantity}")

    market = market_for_ticker(ticker)
    symbol = symbol_for_ticker(ticker)
    currency = currency_for_market(market)
    action = "BUY" if str(side).upper() == "BUY" else "SELL"
    try:
        contract = stock_contract(symbol=symbol, currency=currency)
    except TypeError:
        contract = stock_contract(symbol, currency)

    want_limit = (
        str(order_type).upper() in {"LMT", "LIMIT"}
        or paper
        or market != "US"
        or limit_price is not None
    )
    px = float(limit_price) if limit_price and float(limit_price) > 0 else 0.0
    if want_limit and px <= 0:
        quoted = quote_last_price(quote_client, ticker)
        px = float(quoted) if quoted else 0.0
    if want_limit and px <= 0:
        raise ValueError(
            f"No limit price for {ticker}; market orders cannot reach the Tiger "
            "app outside regular hours"
        )

    if want_limit:
        px = aggressive_limit(action, px, ticker)
        order = limit_order(
            account=account,
            contract=contract,
            action=action,
            quantity=qty,
            limit_price=px,
        )
        try:
            order.time_in_force = "DAY"
        except Exception:
            pass
        if market == "US":
            _apply_us_session(order)
        try:
            order.user_mark = "qat-paper" if paper else "qat-live"
        except Exception:
            pass
        return order

    order = market_order(
        account=account,
        contract=contract,
        action=action,
        quantity=qty,
    )
    try:
        order.time_in_force = "DAY"
        order.outside_rth = False
    except Exception:
        pass
    return order


def order_was_accepted(result: Any) -> bool:
    if result is None:
        return False
    if isinstance(result, dict):
        status = str(result.get("status") or "").upper()
        if status in {"FAILED", "SDK_UNAVAILABLE", "PENDING_CONFIRMATION", "REJECTED"}:
            return False
        if result.get("error"):
            return False
        oid = result.get("order_id") or result.get("id") or result.get("orderId")
        return bool(oid) and status not in {"PAPER_SUBMITTED"}
    return True


def submit_stock_order(
    trade_client: Any,
    *,
    account: str,
    ticker: str,
    side: str,
    quantity: int,
    order_type: str = "MKT",
    limit_price: float | None = None,
    quote_client: Any = None,
    paper: bool = True,
) -> dict[str, Any]:
    """Build an Order and submit it. Returns a status dict (never a fake fill)."""
    order = build_stock_order(
        account=account,
        ticker=ticker,
        side=side,
        quantity=quantity,
        order_type=order_type,
        limit_price=limit_price,
        quote_client=quote_client,
        paper=paper,
    )
    returned = trade_client.place_order(order)
    oid = (
        getattr(order, "id", None)
        or getattr(order, "order_id", None)
        or returned
    )
    status = getattr(order, "status", None) or "SUBMITTED"
    return {
        "order_id": str(oid) if oid not in (None, "") else "",
        "ticker": ticker,
        "side": str(side).upper(),
        "quantity": int(quantity),
        "order_type": getattr(order, "order_type", None) or ("LMT" if paper else order_type),
        "limit_price": getattr(order, "limit_price", None),
        "status": str(status),
        "account": account,
        "outside_rth": bool(getattr(order, "outside_rth", False)),
        "paper": paper,
    }
