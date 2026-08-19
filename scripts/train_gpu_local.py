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


def _normalize_ohlcv(df):
    import pandas as pd

    if df is None or df.empty:
        return None
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = [str(c[0]).lower() for c in out.columns]
    else:
        out.columns = [str(c).lower() for c in out.columns]
    # Flatten common aliases
    rename = {"adj close": "adj_close", "adj_close": "adj_close"}
    out = out.rename(columns=rename)
    if not isinstance(out.index, pd.DatetimeIndex):
        if "date" in out.columns:
            out["date"] = pd.to_datetime(out["date"])
            out = out.set_index("date")
        else:
            out.index = pd.to_datetime(out.index)
    if getattr(out.index, "tz", None) is not None:
        out.index = out.index.tz_localize(None)
    need = {"open", "high", "low", "close"}
    if not need.issubset(set(out.columns)):
        return None
    if "volume" not in out.columns:
        out["volume"] = 0.0
    out = out.sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out if len(out) >= 100 else None


def _parquet_ok(fpath: Path) -> bool:
    try:
        if not fpath.exists() or fpath.stat().st_size < 500:
            return False
        import pandas as pd

        df = _normalize_ohlcv(pd.read_parquet(fpath))
        return df is not None and len(df) >= 100
    except Exception:
        return False


def _download_stooq(ticker: str, years: int = 3):
    """Fallback free daily bars from Stooq (no Yahoo rate limit)."""
    import pandas as pd

    # Stooq US symbols often use lowercase + .us
    sym = f"{ticker.lower()}.us"
    url = f"https://stooq.com/q/d/l/?s={sym}&i=d"
    try:
        raw = pd.read_csv(url)
    except Exception as exc:
        print(f"[warn] stooq {ticker}: {exc}")
        return None
    if raw is None or raw.empty:
        return None
    raw.columns = [str(c).lower() for c in raw.columns]
    if "date" not in raw.columns:
        return None
    raw["date"] = pd.to_datetime(raw["date"])
    raw = raw.set_index("date").sort_index()
    cutoff = raw.index.max() - pd.Timedelta(days=365 * years + 30)
    raw = raw[raw.index >= cutoff]
    return _normalize_ohlcv(raw)


def _download_yahoo_one(ticker: str, years: int, retries: int = 5):
    import yfinance as yf

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            df = yf.download(
                ticker,
                period=f"{years}y",
                interval="1d",
                progress=False,
                auto_adjust=False,
                threads=False,
            )
            norm = _normalize_ohlcv(df)
            if norm is not None:
                return norm
            last_err = "empty"
        except Exception as exc:
            last_err = str(exc)
            msg = str(exc).lower()
            if "rate" in msg or "too many" in msg:
                sleep_s = min(60, 5 * attempt * attempt)
                print(f"[warn] yahoo rate-limit {ticker} attempt {attempt}/{retries}, sleep {sleep_s}s")
                time.sleep(sleep_s)
                continue
            print(f"[warn] yahoo {ticker} attempt {attempt}: {exc}")
            time.sleep(2 * attempt)
    print(f"[warn] yahoo failed {ticker}: {last_err}")
    return None


def _download_sample_csv(ticker: str, years: int = 3):
    """Offline / bundled sample bars shipped in data/sample_daily/."""
    import pandas as pd

    for base in (Path("data/sample_daily"), ROOT / "data" / "sample_daily"):
        fpath = base / f"{ticker}.csv"
        if not fpath.exists():
            continue
        try:
            raw = pd.read_csv(fpath)
        except Exception:
            continue
        raw.columns = [str(c).lower() for c in raw.columns]
        if "date" in raw.columns:
            raw["date"] = pd.to_datetime(raw["date"])
            raw = raw.set_index("date")
        elif "unnamed: 0" in raw.columns:
            raw["unnamed: 0"] = pd.to_datetime(raw["unnamed: 0"])
            raw = raw.set_index("unnamed: 0")
        else:
            # first column may be the index written by to_csv
            raw = pd.read_csv(fpath, index_col=0, parse_dates=True)
        return _normalize_ohlcv(raw)
    return None


def download_tickers(tickers: list[str], years: int = 3, force: bool = False) -> int:
    data_dir = Path("data/daily")
    data_dir.mkdir(parents=True, exist_ok=True)
    n = 0

    # Drop broken / empty caches so we re-fetch
    need: list[str] = []
    for t in tickers:
        fpath = data_dir / f"{t}.parquet"
        if (not force) and _parquet_ok(fpath):
            print(f"[skip] {t} already downloaded ({fpath.stat().st_size} bytes)")
            continue
        if fpath.exists():
            try:
                fpath.unlink()
            except Exception:
                pass
        need.append(t)

    if not need:
        return 0

    # Order: sample CSV (offline) -> Yahoo with backoff -> Stooq
    for t in need:
        print(f"[..] download {t}")
        norm = _download_sample_csv(t, years=years)
        src = "sample"
        if norm is None:
            print(f"[..] yahoo {t}")
            time.sleep(1.0)
            norm = _download_yahoo_one(t, years=years)
            src = "yahoo"
        if norm is None:
            print(f"[..] stooq {t}")
            time.sleep(1.0)
            norm = _download_stooq(t, years=years)
            src = "stooq"
        if norm is None:
            print(f"[warn] {t}: all sources failed")
            continue
        fpath = data_dir / f"{t}.parquet"
        norm.to_parquet(fpath)
        print(f"[ok] {t} rows={len(norm)} ({src})")
        n += 1
        time.sleep(0.5)
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
    parser.add_argument("--force-download", action="store_true", help="Re-download even if parquet exists")
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    device = _ensure_cuda()
    if not args.skip_download:
        n = download_tickers(tickers, years=args.years, force=args.force_download)
        print(f"[ok] downloaded {n} new tickers")
        # Fail early with a clear message if nothing usable
        ok_n = sum(1 for t in tickers if _parquet_ok(Path("data/daily") / f"{t}.parquet"))
        if ok_n < 1:
            raise SystemExit(
                "No usable market data after download (Yahoo rate-limit?). "
                "Wait 10-20 minutes or retry: python scripts/train_gpu_local.py --force-download --tickers AAPL,MSFT,NVDA"
            )
        print(f"[ok] usable parquet files: {ok_n}/{len(tickers)}")
    train_all(tickers, epochs=args.epochs, device=device, skip_rl=args.skip_rl)
    print("\nNext: copy data/models/* to Lightsail C:\\quant-ai-trader\\data\\models\\")
    print("Then on Lightsail: .\\scripts\\windows_deploy.ps1 -SkipInstall")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
