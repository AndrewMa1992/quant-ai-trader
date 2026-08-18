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

1. Retrain models so new scalers / RL meta are on disk:
   ```bash
   python scripts/train_all_models.py   # or train_all_v2.py
   ```
2. Confirm `data/models/` has: `gbdt_v*.joblib`, `transformer_*.pt`, `tcn_*.pt`, `tft_*.pt`, `rl_*.zip` (+ `.meta.json`).
3. Restart infer / pipeline; log should show `N/5 models loaded` with N≥2.

---

## Still open (not this PR)

- Merge backend v1 FinBERT/GAT into v2 ensemble
- Full purged CV as default retrain
- Dedicated single-asset RL policy (v1 multi-ticker obs is still a compromise)
- Online learning / concept-drift auto-rollback
