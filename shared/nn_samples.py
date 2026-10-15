"""Append one compact window per ticker so later training can see what the paper loop saw."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def samples_path(root: Path | None = None) -> Path:
    base = Path(root) if root is not None else Path("data") / "nn_samples"
    base.mkdir(parents=True, exist_ok=True)
    return base / "windows.jsonl"


def record_daily_window(
    ticker: str,
    df: pd.DataFrame,
    *,
    root: Path | None = None,
    lookback: int = 20,
) -> dict | None:
    """Append the latest close and trailing log returns for one symbol.

    The full OHLCV history is stored separately as ``data/daily/{ticker}.parquet``.
    This file is the per-cycle sample the training job can join on later.
    """
    if df is None or getattr(df, "empty", True):
        return None
    work = df.copy()
    work.columns = [str(col).lower() for col in work.columns]
    if "close" not in work.columns:
        return None
    close = pd.to_numeric(work["close"], errors="coerce").dropna()
    if close.empty:
        return None
    returns = []
    for value in (close / close.shift(1)).dropna().tail(lookback).tolist():
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number <= 0:
            continue
        returns.append(round(math.log(number), 6))
    asof = close.index[-1]
    asof_text = asof.isoformat() if hasattr(asof, "isoformat") else str(asof)
    row = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "ticker": ticker,
        "asof": asof_text,
        "rows": int(len(work)),
        "close": float(close.iloc[-1]),
        "log_returns": returns,
    }
    path = samples_path(root)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")
    return row
