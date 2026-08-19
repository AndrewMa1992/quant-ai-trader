"""services/execution_service/live/tca.py – Transaction Cost Analysis (TCA).

Institutional-lite TCA: arrival price vs fill, implementation shortfall (bps),
and ADV participation checks against ``configs.risk_limits.RISK_LIMITS``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from loguru import logger

from configs.risk_limits import RISK_LIMITS


@dataclass
class TCAResult:
    ticker: str
    side: str
    quantity: float
    arrival_price: float
    fill_price: float
    slippage_bps: float
    implementation_shortfall_bps: float
    participation: Optional[float]
    passed: bool
    reason: str = ""


def slippage_bps(side: str, arrival: float, fill: float) -> float:
    if arrival <= 0 or fill <= 0:
        return 0.0
    raw = (fill - arrival) / arrival
    # Buys: positive slippage when fill > arrival; sells opposite
    signed = raw if side.lower() in ("buy", "long") else -raw
    return float(signed * 10_000)


def pre_trade_participation_ok(order_notional: float, adv_usd: float | None) -> tuple[bool, str]:
    if adv_usd is None or adv_usd <= 0:
        return True, "ADV unknown — skipped"
    part = order_notional / adv_usd
    limit = RISK_LIMITS.MAX_ORDER_PARTICIPATION
    if part > limit:
        return False, f"participation {part:.2%} > limit {limit:.2%}"
    return True, f"participation {part:.2%}"


def analyze_fill(
    ticker: str,
    side: str,
    quantity: float,
    arrival_price: float,
    fill_price: float,
    adv_usd: float | None = None,
) -> TCAResult:
    slip = slippage_bps(side, arrival_price, fill_price)
    # Implementation shortfall ≈ slippage for single-fill MKT
    is_bps = slip
    notional = abs(quantity * fill_price)
    part = (notional / adv_usd) if adv_usd and adv_usd > 0 else None

    passed = True
    reason = "OK"
    if abs(slip) > RISK_LIMITS.MAX_SLIPPAGE_BPS:
        passed = False
        reason = f"slippage {slip:.1f}bps > limit {RISK_LIMITS.MAX_SLIPPAGE_BPS}bps"
        logger.warning(f"TCA breach {ticker}: {reason}")

    if part is not None and part > RISK_LIMITS.MAX_ORDER_PARTICIPATION:
        passed = False
        reason = f"participation {part:.2%} > limit {RISK_LIMITS.MAX_ORDER_PARTICIPATION:.2%}"

    return TCAResult(
        ticker=ticker,
        side=side,
        quantity=quantity,
        arrival_price=arrival_price,
        fill_price=fill_price,
        slippage_bps=round(slip, 2),
        implementation_shortfall_bps=round(is_bps, 2),
        participation=None if part is None else round(part, 6),
        passed=passed,
        reason=reason,
    )


def to_dict(result: TCAResult) -> Dict[str, Any]:
    return {
        "ticker": result.ticker,
        "side": result.side,
        "quantity": result.quantity,
        "arrival_price": result.arrival_price,
        "fill_price": result.fill_price,
        "slippage_bps": result.slippage_bps,
        "implementation_shortfall_bps": result.implementation_shortfall_bps,
        "participation": result.participation,
        "passed": result.passed,
        "reason": result.reason,
    }
