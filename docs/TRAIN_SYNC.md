# Local GPU train → automatic sync to Lightsail

## Fully automated loop

1. **GPU PC (one-time):**
   ```powershell
   .\scripts\install_local_train_autostart.ps1 -DailyAt "02:30" -Epochs 40 -RunNow
   ```
   Registers `QAT-Local-TrainSync` (daily train + git push).

2. **Lightsail (already done if you ran):**
   ```powershell
   .\scripts\windows_install_autostart.ps1 -Branch cursor/quant-upgrade-a75f
   ```
   `QAT-Paper-AutoCD` pulls every ~10 min; model-only commits hot-reload without full restart.

```
GPU PC nightly train_and_sync
        ↓ push data/models
GitHub
        ↓ AutoCD ~10 min
Lightsail hot-reload / redeploy
```


```
GPU PC train  →  git push models  →  Lightsail QAT-Paper-AutoCD (≈10 min) pulls + restarts
```

### On your RTX 3060 PC

```powershell
cd <repo>
git fetch origin
git checkout cursor/quant-upgrade-a75f
git reset --hard origin/cursor/quant-upgrade-a75f

pip install torch --index-url https://download.pytorch.org/whl/cu124
pip install yfinance lightgbm xgboost stable-baselines3 gymnasium scikit-learn pandas pyarrow

# Train + push checkpoints to GitHub (Lightsail will auto-pull)
.\scripts\train_and_sync.ps1 -Epochs 40
# faster smoke: .\scripts\train_and_sync.ps1 -Epochs 20 -SkipRl
```

Lightsail must already have:

```powershell
.\scripts\windows_install_autostart.ps1 -Branch cursor/quant-upgrade-a75f
```

Force update immediately on the server (optional):

```powershell
.\scripts\windows_cd_deploy.ps1 -Branch cursor/quant-upgrade-a75f -Force
```

### Notes

- Checkpoints live under `data/models/` and are now allowed in git for AutoCD.
- Single file **>100MB** may fail GitHub push — use SCP path below or Git LFS.
- `[skip ci]` in the commit message avoids unnecessary CI noise.

---

## Alternative: SCP direct to Lightsail (no git models)

1. On Lightsail enable OpenSSH Server + open port **22**.
2. On GPU PC:

```powershell
.\scripts\sync_models_scp.ps1 -HostIp 3.106.139.233 -User Administrator -RestartRemote
```

First `scp`/`ssh` will ask for the Administrator password (or use an SSH key).

---

## Verify on Lightsail

```powershell
Get-ChildItem C:\quant-ai-trader\data\models
Invoke-RestMethod http://127.0.0.1:8001/api/v2/infer/models/status -Headers @{ "X-API-Key"="dev-api-key-change-in-production" }
```
