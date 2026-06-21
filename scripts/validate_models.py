"""Validate all v2 models: load + inference + sanity check."""
from __future__ import annotations
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import torch
from loguru import logger

from configs.settings import settings

device = settings.TRAIN_DEVICE
logger.info(f"Device: {device} | GPU: {torch.cuda.get_device_name(0) if device=='cuda' else 'N/A'}")
logger.info(f"PyTorch: {torch.__version__}")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE, "data", "models")

# ── Load real data from parquet ──
data_path = os.path.join(BASE, "data")
parquet_files = [f for f in os.listdir(data_path) if f.endswith('.parquet')]
logger.info(f"Found {len(parquet_files)} parquet files in data/")

X = None
if parquet_files:
    dfs = []
    for pf in parquet_files[:3]:  # limit to 3 files
        try:
            df = pd.read_parquet(os.path.join(data_path, pf))
            dfs.append(df)
        except Exception as e:
            logger.warning(f"Failed to read {pf}: {e}")
    if dfs:
        combined = pd.concat(dfs, ignore_index=True)
        # Keep numeric columns only
        combined = combined.select_dtypes(include=[np.number])
        combined = combined.dropna(axis=1, thresh=int(len(combined)*0.5))
        X = combined.fillna(0).iloc[-500:]
        logger.info(f"Loaded {len(X)} rows x {X.shape[1]} cols from parquet")

if X is None or len(X) < 70:
    logger.warning("Not enough real data, using synthetic data")
    # Models were trained with 77 features
    N_FEAT = 77
    np.random.seed(42)
    X = pd.DataFrame(
        np.random.randn(200, N_FEAT).astype(np.float32),
        columns=[f"f{i}" for i in range(N_FEAT)]
    )
    logger.info(f"Generated synthetic data: {len(X)} rows x {N_FEAT} cols")

seq_len = min(64, len(X) - 10)
logger.info(f"Using seq_len={seq_len}")

results = {}

# ── 1. TCN ──
logger.info("\n=== Testing TCN ===")
from services.model_train_service.trainers.tcn_trainer import TCNTrainer
tcn = TCNTrainer(seq_len=seq_len, device=device)
try:
    tcn.load(os.path.join(DATA_DIR, "tcn_v2.pt"))
    pred = tcn.predict(X.iloc[-128:])
    valid = bool(np.isfinite(pred).all() and not (pred == 0).all())
    results["TCN"] = {"valid": valid, "pred_range": [float(np.nan_to_num(pred).min()), float(np.nan_to_num(pred).max())],
                       "pred_mean": float(np.nan_to_num(pred).mean()), "pred_std": float(np.nan_to_num(pred).std()),
                       "params": sum(p.numel() for p in tcn.model.parameters())}
    logger.info(f"TCN: valid={valid}, range=[{results['TCN']['pred_range'][0]:.4f}, {results['TCN']['pred_range'][1]:.4f}], "
                f"params={results['TCN']['params']:,}")
except Exception as e:
    results["TCN"] = {"error": str(e)[:200]}
    logger.error(f"TCN FAILED: {e}")

# ── 2. Transformer ──
logger.info("\n=== Testing Transformer ===")
from services.model_train_service.trainers.transformer_trainer import TransformerTrainer
trans = TransformerTrainer(seq_len=seq_len, device=device)
try:
    trans.load(os.path.join(DATA_DIR, "transformer_v2.pt"))
    pred = trans.predict(X.iloc[-128:])
    valid = bool(np.isfinite(pred).all() and not (pred == 0).all())
    results["Transformer"] = {"valid": valid, "pred_range": [float(np.nan_to_num(pred).min()), float(np.nan_to_num(pred).max())],
                               "pred_mean": float(np.nan_to_num(pred).mean()), "pred_std": float(np.nan_to_num(pred).std()),
                               "d_model": trans.d_model, "n_layers": trans.n_layers,
                               "params": sum(p.numel() for p in trans.model.parameters())}
    logger.info(f"Transformer: valid={valid}, d_model={trans.d_model}, layers={trans.n_layers}, "
                f"params={results['Transformer']['params']:,}")
except Exception as e:
    results["Transformer"] = {"error": str(e)[:200]}
    logger.error(f"Transformer FAILED: {e}")

# ── 3. TFT ──
logger.info("\n=== Testing TFT ===")
from services.model_train_service.trainers.tft_trainer import TFTTrainer
tft = TFTTrainer(seq_len=seq_len, device=device)
try:
    tft.load(os.path.join(DATA_DIR, "tft_v2.pt"))
    pred = tft.predict(X.iloc[-128:])
    valid = bool(np.isfinite(pred).all() and not (pred == 0).all())
    qpred = tft.predict_quantiles(X.iloc[-128:])
    results["TFT"] = {"valid": valid, "pred_range": [float(np.nan_to_num(pred).min()), float(np.nan_to_num(pred).max())],
                       "pred_mean": float(np.nan_to_num(pred).mean()), "pred_std": float(np.nan_to_num(pred).std()),
                       "q10_mean": float(np.nan_to_num(qpred["q10"]).mean()),
                       "q90_mean": float(np.nan_to_num(qpred["q90"]).mean()),
                       "params": sum(p.numel() for p in tft.model.parameters())}
    logger.info(f"TFT: valid={valid}, q10={results['TFT']['q10_mean']:.4f}, q90={results['TFT']['q90_mean']:.4f}, "
                f"params={results['TFT']['params']:,}")
except Exception as e:
    results["TFT"] = {"error": str(e)[:200]}
    logger.error(f"TFT FAILED: {e}")

# ── Summary ──
print(f"\n{'='*60}")
print("MODEL VALIDATION REPORT")
print(f"{'='*60}")
for name, r in results.items():
    if "error" in r:
        print(f"  ❌ {name}: {r['error']}")
    elif r["valid"]:
        print(f"  ✅ {name}: params={r.get('params','?'):,}, pred_range={r['pred_range']}")
    else:
        print(f"  ⚠️ {name}: loaded but predictions degenerate")

all_ok = all("error" not in r and r.get("valid", False) for r in results.values())
print(f"\nOverall: {'🎉 ALL 3 DL MODELS VALID' if all_ok else '⚠️ SOME MODELS HAVE ISSUES'}")

# Save report
report_path = os.path.join(BASE, "cache", "model_validation.json")
os.makedirs(os.path.dirname(report_path), exist_ok=True)
with open(report_path, "w") as f:
    json.dump(results, f, indent=2, default=str)
logger.info(f"Report → {report_path}")
