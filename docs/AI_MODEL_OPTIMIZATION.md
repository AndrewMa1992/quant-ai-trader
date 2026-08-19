# AI Model Optimization Notes

**Branch**: optimize v2 train/serve path used by paper trading (`InferenceEngine`).

This does **not** claim RenTec/Two Sigma model parity. It fixes correctness bugs that silently degrade ensemble quality.

---

## Fixes shipped

| Issue | Before | After |
|-------|--------|-------|
| Train/serve skew | Transformer/TCN/TFT ignored checkpoint `StandardScaler` | `preprocess.apply_scaler` on load+predict |
| Feature pad | Silent zeros, full confidence | `confidence_haircut` on missing fraction |
| RL obs mismatch | Raw `X.values` into SB3 → errors → **random noise in signals** | Build `TradingEnv`-compatible window obs; unloaded → **zeros** |
| SAC on Discrete | Could construct SAC on Discrete(3) | Force PPO; refuse SAC load |
| RL meta | No window/feature sidecar | `{model}.zip.meta.json` on save |
| Bayesian / regime | Dead in pipeline | `adapt_from_market` + `update_ensemble_from_signals` each cycle |
| Blender weights | Filtered models still leaked weight mass | Renormalize to active subset |
| FinBERT/GAT cache | bare `CACHE_DIR` NameError | `settings.CACHE_DIR` / `HF_CACHE` |
| v1 RL single-ticker | Mean-clone all virtual slots | Zero-pad other slots + confidence haircut |
| TFT train | No scaler | StandardScaler saved in checkpoint |
| Registry | No freshness signal | Warn if checkpoint >30d old |

---

## Operator checklist

### A) Local RTX 3060 / CUDA desktop (recommended)

Lightsail Windows is CPU-only. Train on the PC with the 3060, then copy checkpoints:

```powershell
git pull
pip install torch --index-url https://download.pytorch.org/whl/cu124
pip install yfinance lightgbm xgboost stable-baselines3 gymnasium scikit-learn
.\scripts\train_gpu_local.ps1 -Epochs 40
# artifacts: data\models\gbdt_v2.joblib transformer_v2.pt tcn_v2.pt tft_v2.pt rl_v2.zip
```

Copy `data\models\*` to Lightsail `C:\quant-ai-trader\data\models\`, then:
`.\scripts\windows_deploy.ps1 -SkipInstall`

Optimizations for 3060: AMP, d_model=256, batch=128, pin_memory.

### B) API / UI on a running stack

1. Ingest tickers (Sync page or `/api/v2/data/ingest`)
2. Models page: choose `transformer` / `gbdt` / `tcn` / `tft` / `rl`
3. Or: `POST /api/v2/train/train/transformer` with `{"tickers":[...],"device":"cuda"}`

Confirm `data/models/` has: `gbdt_v*.joblib`, `transformer_*.pt`, `tcn_*.pt`, `tft_*.pt`, `rl_*.zip` (+ `.meta.json`).
Restart infer / pipeline; log should show `N/5 models loaded` with N≥2.

---

## Still open (not this PR)

- Merge backend v1 FinBERT/GAT into v2 ensemble
- Full purged CV as default retrain
- Dedicated single-asset RL policy (v1 multi-ticker obs is still a compromise)
- Online learning / concept-drift auto-rollback
