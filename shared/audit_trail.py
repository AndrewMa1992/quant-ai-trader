"""shared/audit_trail.py – Institutional cycle / order audit trail.

Writes append-only JSONL under ``cache/audit/`` for compliance review:
signals → risk decisions → target weights → orders → fills → risk snapshot.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

_AUDIT_DIR = Path("cache/audit")


class AuditTrail:
    """Append-only JSONL audit logger."""

    def __init__(self, directory: Path | str | None = None) -> None:
        self.dir = Path(directory) if directory else _AUDIT_DIR
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, kind: str) -> Path:
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        return self.dir / f"{kind}_{day}.jsonl"

    def write(self, kind: str, payload: Dict[str, Any]) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            **payload,
        }
        path = self._path(kind)
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception as exc:
            logger.warning(f"AuditTrail write failed ({kind}): {exc}")

    def cycle(
        self,
        cycle: int,
        trade_date: str,
        *,
        tickers: int = 0,
        signals: int = 0,
        approved: int = 0,
        rejected: int = 0,
        orders: int = 0,
        risk_snapshot: Optional[Dict[str, Any]] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.write(
            "cycle",
            {
                "cycle": cycle,
                "trade_date": trade_date,
                "tickers": tickers,
                "signals": signals,
                "approved": approved,
                "rejected": rejected,
                "orders": orders,
                "risk": risk_snapshot or {},
                **(extra or {}),
            },
        )

    def risk_reject(self, ticker: str, reason: str, details: Optional[Dict] = None) -> None:
        self.write(
            "risk_reject",
            {"ticker": ticker, "reason": reason, "details": details or {}},
        )

    def order(self, order: Dict[str, Any]) -> None:
        self.write("order", {"order": order})


_GLOBAL: Optional[AuditTrail] = None


def get_audit_trail() -> AuditTrail:
    global _GLOBAL
    if _GLOBAL is None:
        _GLOBAL = AuditTrail()
    return _GLOBAL
