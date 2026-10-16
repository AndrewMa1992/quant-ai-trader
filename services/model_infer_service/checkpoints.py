"""Ensemble checkpoints published by the GPU training machine."""

from __future__ import annotations

from pathlib import Path

CHECKPOINT_NAMES: tuple[str, ...] = (
    "gbdt_v2.joblib",
    "transformer_v2.pt",
    "tcn_v2.pt",
    "tft_v2.pt",
    "rl_v2.zip",
)


def checkpoint_mtime(root: str | Path = "data/models") -> float:
    """Newest mtime among the ensemble files, or 0 when none exist."""
    base = Path(root)
    stamp = 0.0
    for name in CHECKPOINT_NAMES:
        path = base / name
        if path.is_file():
            stamp = max(stamp, path.stat().st_mtime)
    return stamp
