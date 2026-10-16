"""Factor statistics from stored daily bars.

IC, decay, and correlation are computed from parquet OHLCV.
No random series are substituted when bars are missing.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np
import pandas as pd

_FRAME_CACHE: dict[str, Any] = {"at": 0.0, "frames": None}
_SUMMARY_CACHE: dict[str, Any] = {"at": 0.0, "rows": None}
_ENGINE: Any = None

_CACHE_SECONDS = 600
_MAX_NAMES = 12
_MIN_ROWS = 40
_TAIL_ROWS = 160


def _engine():
    global _ENGINE
    if _ENGINE is None:
        from services.factor_service.engine.factor_engine import FactorEngine

        engine = FactorEngine()
        engine.register_all()
        _ENGINE = engine
    return _ENGINE


def resolve_factor_id(token: str) -> str | None:
    """Accept a factor id (F001) or its short name (ret_1m)."""
    text = (token or "").strip()
    if not text:
        return None
    from configs.factor_registry import FACTOR_REGISTRY, get_factor_by_id

    if get_factor_by_id(text) is not None:
        return text
    upper = text.upper()
    if get_factor_by_id(upper) is not None:
        return upper
    for entries in FACTOR_REGISTRY.values():
        for entry in entries:
            if entry.get("name") == text or entry.get("id") == text:
                return str(entry["id"])
    return None


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(col).lower() for col in out.columns]
    if not isinstance(out.index, pd.DatetimeIndex):
        if "date" in out.columns:
            out["date"] = pd.to_datetime(out["date"])
            out = out.set_index("date")
        else:
            return out.iloc[0:0]
    if getattr(out.index, "tz", None) is not None:
        out.index = out.index.tz_localize(None)
    return out.sort_index()


def load_ohlcv(max_names: int = _MAX_NAMES) -> dict[str, pd.DataFrame]:
    """Load the stored daily bars used for live factor stats."""
    now = time.time()
    cached = _FRAME_CACHE.get("frames")
    if isinstance(cached, dict) and now - float(_FRAME_CACHE.get("at") or 0) < _CACHE_SECONDS:
        return cached

    from services.data_service.storage.parquet_store import ParquetStore

    frames: dict[str, pd.DataFrame] = {}
    store = ParquetStore()
    for ticker in store.list_tickers():
        if len(frames) >= max_names:
            break
        raw = store.read_daily(ticker)
        if raw is None or len(raw) < _MIN_ROWS:
            continue
        df = _normalize_ohlcv(raw).tail(_TAIL_ROWS)
        if df.empty or "close" not in df.columns:
            continue
        frames[ticker] = df

    _FRAME_CACHE["at"] = now
    _FRAME_CACHE["frames"] = frames
    return frames


def _forward_returns(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    columns: dict[str, pd.Series] = {}
    for ticker, df in frames.items():
        price = df["adj_close"] if "adj_close" in df.columns else df["close"]
        columns[ticker] = price.pct_change().shift(-1)
    return pd.DataFrame(columns)


def factor_frame(factor_id: str, frames: dict[str, pd.DataFrame] | None = None) -> pd.DataFrame:
    """Dates × tickers for one factor. Empty when the factor cannot be computed."""
    frames = frames if frames is not None else load_ohlcv()
    resolved = resolve_factor_id(factor_id) or factor_id
    columns: dict[str, pd.Series] = {}
    engine = _engine()
    for ticker, df in frames.items():
        try:
            series = engine.compute(df, resolved)
        except Exception:
            continue
        if series is None or len(series) == 0:
            continue
        columns[ticker] = pd.Series(series, index=df.index).astype(float)
    if not columns:
        return pd.DataFrame()
    return pd.DataFrame(columns)


def _per_name_ics(factor_df: pd.DataFrame, ret_df: pd.DataFrame) -> list[float]:
    ics: list[float] = []
    for column in factor_df.columns:
        if column not in ret_df.columns:
            continue
        pair = pd.concat(
            [factor_df[column].rename("f"), ret_df[column].rename("r")],
            axis=1,
        ).dropna()
        if len(pair) < 30:
            continue
        ic = pair["f"].corr(pair["r"], method="spearman")
        if pd.notna(ic):
            ics.append(float(ic))
    return ics


def summarize_ics(ics: list[float]) -> dict[str, float] | None:
    if not ics:
        return None
    arr = np.asarray(ics, dtype=float)
    mean = float(arr.mean())
    std = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
    ir = mean / std if std > 0 else 0.0
    t_stat = mean / (std / np.sqrt(len(arr))) if std > 0 else 0.0
    return {
        "rank_ic_mean": round(mean, 6),
        "rank_ic_std": round(std, 6),
        "information_ratio": round(ir, 4),
        "ic_t_stat": round(t_stat, 4),
        "positive_ic_ratio": round(float((arr > 0).mean()), 4),
        "num_observations": float(len(arr)),
    }


def ic_series(factor_id: str) -> dict[str, Any]:
    """Daily cross-sectional rank IC for one factor, from stored bars."""
    frames = load_ohlcv()
    if not frames:
        return {"ic_series": [], "ic_cumulative": [], "source": "no_bars"}

    factor_df = factor_frame(factor_id, frames)
    ret_df = _forward_returns(frames)
    if factor_df.empty:
        return {"ic_series": [], "ic_cumulative": [], "source": "factor_unavailable"}

    dates = factor_df.index.intersection(ret_df.index)
    points: list[dict[str, Any]] = []
    for dt in dates:
        aligned = pd.concat(
            [factor_df.loc[dt].rename("f"), ret_df.loc[dt].rename("r")],
            axis=1,
        ).dropna()
        if len(aligned) < 4:
            continue
        ic = aligned["f"].corr(aligned["r"], method="spearman")
        if pd.notna(ic):
            stamp = pd.Timestamp(dt)
            points.append({"date": stamp.date().isoformat(), "ic": float(ic)})

    if len(points) < 5:
        # Too few names for a cross-section. Use each name's own rank IC.
        per_name = _per_name_ics(factor_df, ret_df)
        summary = summarize_ics(per_name) or {}
        return {
            **summary,
            "ic_series": [
                {"date": f"name-{i + 1}", "ic": round(v, 6)} for i, v in enumerate(per_name)
            ],
            "ic_cumulative": [],
            "monthly_ic": [],
            "source": "stored_bars",
        }

    cumulative = 0.0
    series = []
    cumulative_series = []
    for point in points:
        cumulative += point["ic"]
        series.append({"date": point["date"], "ic": round(point["ic"], 6)})
        cumulative_series.append(
            {"date": point["date"], "cumulative_ic": round(cumulative, 6)}
        )
    summary = summarize_ics([p["ic"] for p in points]) or {}
    return {
        **summary,
        "ic_series": series,
        "ic_cumulative": cumulative_series,
        "monthly_ic": [],
        "source": "stored_bars",
    }


def ic_summary(limit: int = 40) -> list[dict[str, Any]]:
    """IC mean / IR for factors that can be computed on stored bars."""
    now = time.time()
    cached = _SUMMARY_CACHE.get("rows")
    if isinstance(cached, list) and now - float(_SUMMARY_CACHE.get("at") or 0) < _CACHE_SECONDS:
        return cached[:limit]

    from configs.factor_registry import get_all_factor_ids, get_factor_by_id

    frames = load_ohlcv()
    rows: list[dict[str, Any]] = []
    if frames:
        ret_df = _forward_returns(frames)
        for factor_id in get_all_factor_ids():
            if len(rows) >= limit:
                break
            factor_df = factor_frame(factor_id, frames)
            stats = summarize_ics(_per_name_ics(factor_df, ret_df))
            if stats is None:
                continue
            meta = get_factor_by_id(factor_id) or {}
            rows.append(
                {
                    "id": factor_id,
                    "name": meta.get("name") or factor_id,
                    "category": meta.get("category") or "",
                    "ic_mean": stats["rank_ic_mean"],
                    "ic_std": stats["rank_ic_std"],
                    "ir": stats["information_ratio"],
                    "observations": int(stats["num_observations"]),
                }
            )
    _SUMMARY_CACHE["at"] = now
    _SUMMARY_CACHE["rows"] = rows
    return rows


def correlation_matrix(factor_ids: list[str]) -> tuple[pd.DataFrame, list[str]]:
    """Correlation of live factor series (cross-sectional mean per day)."""
    frames = load_ohlcv()
    series: dict[str, pd.Series] = {}
    for raw_id in factor_ids:
        factor_id = resolve_factor_id(raw_id)
        if not factor_id or not frames:
            continue
        frame = factor_frame(factor_id, frames)
        if frame.empty:
            continue
        series[factor_id] = frame.mean(axis=1)
    if len(series) < 2:
        return pd.DataFrame(), list(series)
    panel = pd.DataFrame(series).dropna(how="all")
    return panel.corr(method="spearman"), list(panel.columns)


def mean_factor_and_returns(factor_id: str) -> tuple[pd.Series, pd.Series]:
    """Equal-weight factor and next-day return, for decay analysis."""
    frames = load_ohlcv()
    empty = pd.Series(dtype=float)
    if not frames:
        return empty, empty
    factor_df = factor_frame(factor_id, frames)
    ret_df = _forward_returns(frames)
    if factor_df.empty:
        return empty, empty
    # Decay wants same-day returns, then shifts them by lag itself.
    # Rebuild contemporaneous daily returns (not already shifted).
    daily: dict[str, pd.Series] = {}
    for ticker, df in frames.items():
        price = df["adj_close"] if "adj_close" in df.columns else df["close"]
        daily[ticker] = price.pct_change()
    returns = pd.DataFrame(daily).mean(axis=1)
    factor = factor_df.mean(axis=1)
    return factor, returns
