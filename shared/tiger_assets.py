"""Parse Tiger OpenAPI account / position / order payloads into dicts.

Paper (sandbox) accounts often store virtual cash in *segment* objects
(``SEC`` / ``FUT``) rather than ``summary.cash``.  Reading only the
top-level summary therefore reports NAV=0 even when the Tiger App shows
funds.  This module walks every known alias and falls back to segments
when the summary is empty.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Optional


def _to_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        parsed = float(val)
    except (TypeError, ValueError):
        return None
    if math.isinf(parsed) or math.isnan(parsed):
        return None
    return parsed


def _first_attr(obj: Any, *names: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        for n in names:
            if n in obj and obj[n] is not None:
                return obj[n]
        return default
    for n in names:
        if hasattr(obj, n):
            v = getattr(obj, n)
            if v is not None:
                return v
    return default


def _first_float(obj: Any, *names: str, default: float = 0.0) -> float:
    v = _first_attr(obj, *names, default=None)
    parsed = _to_float(v)
    return parsed if parsed is not None else default


def _iter_segments(raw: Any) -> list[Any]:
    segments = _first_attr(raw, "segments") or []
    if isinstance(segments, dict):
        return list(segments.values())
    try:
        return list(segments)
    except TypeError:
        return []


def _pick_account(raw: Any, account: str) -> Any:
    """Unwrap ``get_assets()`` list / single PortfolioAccount."""
    if raw is None:
        return None
    rows: list[Any]
    if isinstance(raw, (list, tuple)):
        rows = list(raw)
    else:
        rows = [raw]
    if not rows:
        return None
    want = str(account or "").strip()
    if want:
        for item in rows:
            acc_id = str(_first_attr(item, "account", default="") or "")
            if acc_id == want:
                return item
    return rows[0]


def parse_account_summary(raw: Any, *, account: str = "") -> dict[str, Any]:
    """Normalize ``client.get_assets()`` / ``get_prime_assets()`` output.

    Returns keys used by the rest of the stack::

        account, cash, nav, net_liquidation, total_value, buying_power,
        gross_position_value, currency, unrealized_pnl, realized_pnl,
        available_funds, equity, segments, source
    """
    empty = {
        "account": account,
        "cash": 0.0,
        "nav": 0.0,
        "net_liquidation": 0.0,
        "total_value": 0.0,
        "buying_power": 0.0,
        "gross_position_value": 0.0,
        "currency": "USD",
        "unrealized_pnl": 0.0,
        "realized_pnl": 0.0,
        "available_funds": 0.0,
        "equity": 0.0,
        "segments": [],
        "source": "empty",
    }
    chosen = _pick_account(raw, account)
    if chosen is None:
        return empty

    acc_id = str(_first_attr(chosen, "account", default=account) or account)
    summary = _first_attr(chosen, "summary") or chosen
    cash = _first_float(
        summary,
        "cash",
        "cash_balance",
        "available_cash",
        "settled_cash",
        "accrued_cash",
    )
    nav = _first_float(
        summary,
        "net_liquidation",
        "net_liquidation_value",
        "equity_with_loan",
        "equity",
        "net_liq",
        "total_equity",
        "asset",
        "nav",
    )
    buying_power = _first_float(
        summary,
        "buying_power",
        "available_buying_power",
        "excess_liquidity",
        "sma",
    )
    available_funds = _first_float(
        summary,
        "available_funds",
        "available_cash",
        "cash_available_for_trade",
        "cash_available",
    )
    gpv = _first_float(summary, "gross_position_value", "gross_position")
    unrealized = _first_float(summary, "unrealized_pnl", "unrealizedPnl", "unrlzd_pnl")
    realized = _first_float(summary, "realized_pnl", "realizedPnl")
    currency = str(_first_attr(summary, "currency", default="USD") or "USD")

    segments_out: list[dict[str, Any]] = []
    seg_cash = 0.0
    seg_nav = 0.0
    seg_bp = 0.0
    for seg in _iter_segments(chosen):
        scash = _first_float(seg, "cash", "cash_balance", "available_funds")
        snav = _first_float(
            seg,
            "net_liquidation",
            "equity_with_loan",
            "equity",
            "nlv",
            "asset",
        )
        sbp = _first_float(seg, "buying_power", "available_funds", "excess_liquidity")
        currency_seg = str(_first_attr(seg, "currency", default=currency) or currency)
        cap = str(_first_attr(seg, "capability", "segment", "category", default="") or "")
        segments_out.append({
            "capability": cap,
            "cash": scash,
            "net_liquidation": snav,
            "buying_power": sbp,
            "currency": currency_seg,
        })
        seg_cash += scash
        seg_nav += snav
        seg_bp += sbp

    # Paper accounts frequently leave summary.cash/NAV at 0 while the
    # per-segment books hold the virtual funds.  Only fold segments in
    # when the summary itself is empty — never double-count.
    if cash <= 0 and seg_cash > 0:
        cash = seg_cash
    if nav <= 0 and seg_nav > 0:
        nav = seg_nav
    if buying_power <= 0 and seg_bp > 0:
        buying_power = seg_bp
    if available_funds <= 0 and cash > 0:
        available_funds = cash
    if buying_power <= 0 and cash > 0:
        buying_power = cash
    if nav <= 0 and cash > 0:
        nav = cash + gpv

    return {
        "account": acc_id or account,
        "cash": round(cash, 4),
        "nav": round(nav, 4),
        "net_liquidation": round(nav, 4),
        "total_value": round(nav, 4),
        "buying_power": round(buying_power, 4),
        "gross_position_value": round(gpv, 4),
        "currency": currency,
        "unrealized_pnl": round(unrealized, 4),
        "realized_pnl": round(realized, 4),
        "available_funds": round(available_funds, 4),
        "equity": round(nav, 4),
        "segments": segments_out,
        "source": "tiger_openapi",
    }


def _contract_symbol(obj: Any) -> str:
    contract = _first_attr(obj, "contract")
    if contract is not None:
        sym = _first_attr(contract, "symbol", "contract_code", "identifier", default="")
        if sym:
            return str(sym)
    return str(_first_attr(obj, "contract_code", "symbol", "identifier", "ticker", default="") or "")


def parse_position(pos: Any) -> dict[str, Any]:
    symbol = _contract_symbol(pos)
    qty = _first_float(pos, "quantity", "position", "qty", "shares")
    avg = _first_float(pos, "average_cost", "averageCost", "avg_cost", "average_price")
    mkt = _first_float(pos, "market_price", "marketPrice", "latest_price", "last_price")
    mv = _first_float(pos, "market_value", "marketValue")
    upnl = _first_float(pos, "unrealized_pnl", "unrealizedPnl", "unrlzd_pnl")
    currency = str(_first_attr(pos, "currency", default="USD") or "USD")
    if mkt <= 0 and qty and avg:
        mkt = avg
    if mv <= 0 and qty and mkt:
        mv = qty * mkt
    return {
        "ticker": symbol,
        "symbol": symbol,
        "quantity": qty,
        "shares": qty,
        "average_cost": avg,
        "avg_cost": avg,
        "market_price": mkt,
        "market_value": mv,
        "unrealized_pnl": upnl,
        "currency": currency,
        "side": "long" if qty >= 0 else "short",
    }


def parse_order(order: Any) -> dict[str, Any]:
    oid = _first_attr(order, "id", "order_id", "orderId", default=None)
    symbol = _contract_symbol(order)
    side_raw = str(_first_attr(order, "action", "side", default="BUY") or "BUY").upper()
    side = "BUY" if "BUY" in side_raw else "SELL"
    qty = _first_float(order, "quantity", "total_quantity", "qty")
    filled = _first_float(order, "filled", "filled_quantity", "filledQty")
    remaining = max(0.0, qty - filled)
    status = str(_first_attr(order, "status", default="UNKNOWN") or "UNKNOWN")
    price = _first_float(order, "limit_price", "price", "avg_fill_price")
    avg_fill = _first_float(order, "avg_fill_price", "average_filled_price")
    reason = str(_first_attr(order, "reason", "status_desc", "message", default="") or "")
    currency = str(_first_attr(order, "currency", default="USD") or "USD")
    oid_s = str(oid) if oid is not None else ""
    return {
        "id": oid_s,
        "order_id": oid_s,
        "ticker": symbol,
        "symbol": symbol,
        "side": side,
        "action": side,
        "quantity": qty,
        "filled_qty": filled,
        "filled_quantity": filled,
        "remaining_qty": remaining,
        "status": status,
        "price": price,
        "avg_fill_price": avg_fill,
        "reason": reason,
        "currency": currency,
        "source": "tiger",
    }


def merge_orders(*groups: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate order dicts by ``order_id`` / ``id``."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for group in groups:
        for row in group or []:
            key = str(row.get("order_id") or row.get("id") or "")
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            out.append(row)
    return out
