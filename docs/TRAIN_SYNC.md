# Local GPU train → paper server inference

The paper server does not train. It tracks GitHub `main`, loads `data/models/`, and trades. The RTX 3060 PC trains and pushes those checkpoints.

```
03:00  GPU PC        QAT-Local-TrainSync → pull main → CUDA train → push data/models to main
~2 min paper server QAT-Auto-Deploy     → model-only commits reload checkpoints, no retrain
```

`data/daily/*.parquet` already on `main` is the training set. If Yahoo works on the GPU PC, install with `-UseLocalDownload` instead of waiting for a data push. An older scheduled task that still passes `-Branch cursor/quant-upgrade-a75f` is redirected to `main`.

### One-time setup

**1) Paper server**

`QAT-Auto-Deploy` already polls `origin/main`. A commit that only touches `data/models/` checks out the new files and hot-reloads inference. The paper loop reloads the same files on its next cycle. Code changes still do a full redeploy.

**2) RTX 3060 PC (Admin PowerShell)**

```powershell
cd C:\Quant_Trader
git fetch origin
git reset --hard origin/main

.\scripts\bootstrap_local_gpu.ps1 -RepoRoot C:\Quant_Trader -DailyAt "03:00" -Epochs 40 -SkipRl
# or, when this PC should download bars itself:
# .\scripts\install_local_train_autostart.ps1 -DailyAt "03:00" -Epochs 40 -SkipRl -UseLocalDownload
```

Keep the GPU PC **logged in** around 03:00. **Screen lock (Win+L) is fine** — the Interactive task still runs. **Sleep/hibernate** is the problem; the task uses `WakeToRun` + `StartWhenAvailable`. Also set Windows: *Settings → System → Power → Sleep → Never* (or only after the train window).

### Verify tasks

```powershell
Get-ScheduledTask -TaskName QAT-* | Format-Table TaskName, State
```

Logs:

- Paper server: `C:\quant-ai-trader\logs\auto-deploy.log`
- GPU: `C:\Quant_Trader\logs\gpu-train-*.log`

### Manual run (same scripts the tasks call)

```powershell
# GPU (uses data/daily from origin/main)
.\scripts\train_from_lightsail_data.ps1 -Epochs 40 -SkipRl
```

---

## Option B — GPU downloads itself (when Yahoo works at home)

```powershell
.\scripts\install_local_train_autostart.ps1 -DailyAt "02:30" -Epochs 40 -SkipRl -UseLocalDownload
```

---

## Notes

- Checkpoints live under `data/models/` and are tracked for AutoCD.
- Single file **>100MB** may fail GitHub push — use SCP path below or Git LFS.
- `[skip ci]` in commit messages avoids unnecessary CI noise.
- Scripts auto-set local `git user.name` / `user.email` if missing (not GitHub login).

---

## Alternative: SCP direct to Lightsail (no git models)

1. On Lightsail enable OpenSSH Server + open port **22**.
2. On GPU PC:

```powershell
.\scripts\sync_models_scp.ps1 -HostIp 3.106.139.233 -User Administrator -RestartRemote
```

---

## Verify on the paper server

```powershell
Get-ChildItem C:\quant-ai-trader\data\models
Invoke-RestMethod http://127.0.0.1:8001/api/v2/infer/models/status -Headers @{ "X-API-Key"="dev-api-key-change-in-production" }
```
