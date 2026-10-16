"""Cash-only order sizing.

Buying power is a margin facility. It is never spendable cash.
A buy is allowed only when broker cash can pay for it.
"""

from __future__ import annotations

CASH_USAGE = 0.95
LEVERAGE_CASH_FLOOR = -1.0


def spendable_cash(cash: float, usage: float = CASH_USAGE) -> float:
    """Cash that may be used for a buy. Negative or zero cash spends nothing."""
    try:
        cash_f = float(cash)
        usage_f = float(usage)
    except (TypeError, ValueError):
        return 0.0
    if cash_f <= 0 or usage_f <= 0:
        return 0.0
    return cash_f * usage_f


def cap_buy_quantity(
    quantity: float,
    price: float,
    cash: float,
    usage: float = CASH_USAGE,
) -> float:
    """Largest share count that fits in ``usage`` of ``cash``.

    Returns 0 when cash is not positive, the price is not positive,
    or the requested quantity is not positive.
    """
    try:
        qty = float(quantity)
        px = float(price)
    except (TypeError, ValueError):
        return 0.0
    if qty <= 0 or px <= 0:
        return 0.0
    budget = spendable_cash(cash, usage)
    if budget <= 0:
        return 0.0
    return max(0.0, min(qty, budget / px))


def account_is_levered(account: dict | None) -> bool:
    """True when the account is already using margin.

    Negative cash is borrowed cash. A reported leverage above 1.001
    is the same condition. Buying power above cash, by itself, is not:
    a margin account always advertises extra buying power.
    """
    if not account:
        return False
    try:
        cash = float(account.get("cash", 0) or 0)
    except (TypeError, ValueError):
        cash = 0.0
    try:
        leverage = float(account.get("leverage", 1.0) or 1.0)
    except (TypeError, ValueError):
        leverage = 1.0
    return cash < LEVERAGE_CASH_FLOOR or leverage > 1.001
