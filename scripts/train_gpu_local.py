#!/usr/bin/env python3
"""Local GPU training for RTX 3060 / CUDA desktops.

Downloads OHLCV -> builds factors -> trains ensemble models used by InferenceEngine:
  gbdt_v2.joblib, transformer_v2.pt, tcn_v2.pt, tft_v2.pt, rl_v2.zip

Usage (on the machine WITH the 3060, not Lightsail CPU):
  pip install torch --index-url https://download.pytorch.org/whl/cu124
  pip install yfinance lightgbm xgboost stable-baselines3 gymnasium
  python scripts/train_gpu_local.py
  python scripts/train_gpu_local.py --tickers AAPL,MSFT,GOOGL,SPY,NVDA --epochs 40

Then copy data/models/* to Lightsail C:\\quant-ai-trader\\data\\models\\ and restart infer.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def _ensure_cuda() -> str:
    import torch

    if torch.cuda.is_available():
        name = torch.cuda.get_device_name(0)
        print(f"[ok] CUDA: {name} | capability={torch.cuda.get_device_capability(0)}")
        return "cuda"
    print("[warn] CUDA not available — training on CPU (slow)")
    return "cpu"


def download_tickers(tickers: list[str], years: int = 3) -> int:
    import time as _time

    import yfinance as yf
    import pandas as pd

    data_dir = Path("data/daily")
    data_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for t in tickers:
        fpath = data_dir / f"{t}.parquet"
        if fpath.exists() and fpath.stat().st_size > 1000:
            print(f"[skip] {t} already downloaded")
            continue
        print(f"[..] download {t}")
        df = yf.download(t, period=f"{years}y", interval="1d", progress=False, auto_adjust=False)
        if df is None or df.empty or len(df) < 100:
            print(f"[warn] {t}: insufficient rows")
            continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [str(c[0]).lower() for c in df.columns]
        else:
            df.columns = [str(c).lower() for c in df.columns]
        df.to_parquet(fpath)
        n += 1
        _time.sleep(0.3)
    return n


def train_all(tickers: list[str], epochs: int, device: str, skip_rl: bool) -> dict:
    from services.model_train_service.config import train_config
    from services.model_train_service.data_loader import create_dataset
    from services.model_train_service.trainers.gbdt_trainer import GBDTTrainer
    from services.model_train_service.trainers.transformer_trainer import TransformerTrainer
    from services.model_train_service.trainers.tcn_trainer import TCNTrainer
    from services.model_train_service.trainers.tft_trainer import TFTTrainer

    os.environ["QAT_TRAIN_DEVICE"] = device
    train_config.DEVICE = device  # type: ignore[misc]

    end = time.strftime("%Y-%m-%d")
    print(f"[..] build dataset tickers={tickers}")
    df = create_dataset(tickers, start_date="2021-01-01", end_date=end)
    if df is None or len(df) < 200:
        raise SystemExit("Insufficient training data — check downloads / parquet under data/daily")

    features = df.select_dtypes(include=["number"]).drop(columns=["target"], errors="ignore")
    target = df["target"] if "target" in df.columns else features.iloc[:, 0]
    features = features.replace([float("inf"), float("-inf")], float("nan")).fillna(0.0)
    target = target.fillna(0.0)

    save_dir = Path(train_config.MODEL_SAVE_DIR)
    save_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict] = {}

    # 1) LightGBM (CPU-strong, still part of ensemble)
    print("[..] train GBDT (lightgbm)")
    gbdt = GBDTTrainer(gbdt_type="lightgbm")
    metrics = gbdt.fit(features, (target > 0).astype(int))
    gbdt.save(str(save_dir / "gbdt_v2.joblib"))
    results["gbdt"] = metrics
    print(f"[ok] gbdt -> {metrics}")

    # 2) PatchTST Transformer (GPU + AMP)
    print(f"[..] train Transformer on {device} epochs={epochs}")
    tr = TransformerTrainer(device=device)
    metrics = tr.fit(features, target.clip(-0.5, 0.5), epochs=epochs, batch_size=train_config.BATCH_SIZE)
    tr.save(str(save_dir / "transformer_v2.pt"))
    results["transformer"] = metrics
    print(f"[ok] transformer -> {metrics}")

    # 3) TCN
    print(f"[..] train TCN on {device}")
    tcn = TCNTrainer(device=device)
    metrics = tcn.fit(features, target.clip(-0.5, 0.5), epochs=max(20, epochs // 2), batch_size=train_config.BATCH_SIZE)
    tcn.save(str(save_dir / "tcn_v2.pt"))
    results["tcn"] = metrics
    print(f"[ok] tcn -> {metrics}")

    # 4) TFT
    print(f"[..] train TFT on {device}")
    tft = TFTTrainer(device=device)
    metrics = tft.fit(features, target.clip(-0.5, 0.5), epochs=max(20, epochs // 2), batch_size=train_config.BATCH_SIZE)
    tft.save(str(save_dir / "tft_v2.pt"))
    results["tft"] = metrics
    print(f"[ok] tft -> {metrics}")

    # 5) PPO RL (optional — slower)
    if not skip_rl:
        print(f"[..] train RL PPO on {device}")
        from services.model_train_service.trainers.rl_trainer import RLTrainer

        rl = RLTrainer(device=device, algo="PPO")
        metrics = rl.fit(features, target, total_timesteps=min(train_config.RL_TIMESTEPS, 100_000))
        rl.save(str(save_dir / "rl_v2.zip"))
        results["rl"] = metrics
        print(f"[ok] rl -> {metrics}")
    else:
        print("[skip] RL")

    print("[ok] artifacts:")
    for p in sorted(save_dir.glob("*")):
        print(f"  {p.name:30s} {p.stat().st_size:10d} bytes")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Train QAT ensemble on local CUDA GPU")
    parser.add_argument(
        "--tickers",
        default="AAPL,MSFT,GOOGL,AMZN,NVDA,META,TSLA,SPY,QQQ,IWM",
        help="Comma-separated tickers",
    )
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--skip-rl", action="store_true")
    parser.add_argument("--skip-download", action="store_true")
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    device = _ensure_cuda()
    if not args.skip_download:
        n = download_tickers(tickers, years=args.years)
        print(f"[ok] downloaded {n} new tickers")
    train_all(tickers, epochs=args.epochs, device=device, skip_rl=args.skip_rl)
    print("\nNext: copy data/models/* to Lightsail C:\\quant-ai-trader\\data\\models\\")
    print("Then on Lightsail: .\\scripts\\windows_deploy.ps1 -SkipInstall")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
