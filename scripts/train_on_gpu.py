"""scripts/train_on_gpu.py – Convenience wrapper around paper training pipeline.

Uses auto device detection (CUDA when available, else CPU).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

os.environ.setdefault("QAT_EXECUTION_MODE", "paper")
os.environ.setdefault("QAT_TRADING_SIMULATION_MODE", "true")

try:
    import torch

    os.environ["QAT_TRAIN_DEVICE"] = "cuda" if torch.cuda.is_available() else "cpu"
except Exception:
    os.environ["QAT_TRAIN_DEVICE"] = "cpu"

# Reuse the paper training entrypoint
from scripts.run_paper_train import main

if __name__ == "__main__":
    # Default to a broader model set when invoked as GPU trainer
    if "--models" not in sys.argv:
        sys.argv.extend(["--models", "gbdt,transformer,tcn"])
    raise SystemExit(main())
