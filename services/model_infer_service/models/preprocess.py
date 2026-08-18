"""services/model_infer_service/models/preprocess.py – Train/serve feature alignment.

Ensures inference applies the same column order and StandardScaler used at train time.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

import numpy as np
import pandas as pd
from loguru import logger


def align_features(
    X: pd.DataFrame,
    feature_names: Sequence[str] | None,
    *,
    fill_value: float = 0.0,
) -> tuple[pd.DataFrame, float]:
    """Align ``X`` to training feature order.

    Returns:
        (aligned_df, missing_fraction) where missing_fraction ∈ [0, 1]
        is the share of expected columns absent from ``X``.
    """
    if not feature_names:
        arr = X.fillna(fill_value)
        return arr, 0.0

    names = list(feature_names)
    present = [c for c in names if c in X.columns]
    missing = [c for c in names if c not in X.columns]
    missing_frac = (len(missing) / len(names)) if names else 0.0

    if missing:
        logger.debug(
            f"Feature align: {len(missing)}/{len(names)} missing "
            f"(e.g. {missing[:3]})"
        )

    aligned = pd.DataFrame(fill_value, index=X.index, columns=names, dtype=np.float64)
    for col in present:
        aligned[col] = pd.to_numeric(X[col], errors="coerce")
    return aligned.fillna(fill_value), float(missing_frac)


def apply_scaler(
    X: pd.DataFrame | np.ndarray,
    scaler: Any | None,
) -> np.ndarray:
    """Apply a fitted sklearn StandardScaler if present; else return float32 array."""
    arr = X.values if isinstance(X, pd.DataFrame) else np.asarray(X)
    arr = np.nan_to_num(arr.astype(np.float64), nan=0.0, posinf=1.0, neginf=-1.0)
    if scaler is None:
        return arr.astype(np.float32)
    try:
        return scaler.transform(arr).astype(np.float32)
    except Exception as exc:
        logger.warning(f"Scaler transform failed ({exc}); using raw features")
        return arr.astype(np.float32)


def load_checkpoint_meta(data: dict) -> tuple[list[str], Any, dict]:
    """Extract feature_names, scaler, config from a torch checkpoint dict."""
    feature_names = list(data.get("feature_names") or [])
    scaler = data.get("scaler")
    config = dict(data.get("config") or {})
    return feature_names, scaler, config


def build_rolling_sequences(
    X_arr: np.ndarray,
    seq_len: int,
) -> np.ndarray:
    """Build rolling windows of shape (n_windows, seq_len, n_features)."""
    n = len(X_arr) - seq_len
    if n < 1:
        return np.zeros((0, seq_len, X_arr.shape[1] if X_arr.ndim > 1 else 1), dtype=np.float32)
    return np.array(
        [X_arr[i : i + seq_len] for i in range(n)],
        dtype=np.float32,
    )


def confidence_haircut(base_confidence: float, missing_fraction: float) -> float:
    """Down-weight confidence when features were zero-padded."""
    if missing_fraction <= 0:
        return float(np.clip(base_confidence, 0.0, 1.0))
    # Linear haircut: 50% missing → ~0.5× confidence
    factor = max(0.25, 1.0 - missing_fraction)
    return float(np.clip(base_confidence * factor, 0.0, 1.0))
