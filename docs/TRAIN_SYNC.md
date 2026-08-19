# Local GPU train → automatic sync to Lightsail

## Fully automated daily loop (recommended)

```
01:00  Lightsail  QAT-Data-Download   → download Yahoo via Sydney → push data/daily
03:00  GPU PC     QAT-Local-TrainSync → pull data → CUDA train → push data/models
~10m   Lightsail  QAT-Paper-AutoCD    → pull models → hot-reload paper stack
```

### One-time setup

**1) Lightsail (Admin PowerShell)**

```powershell
cd C:\quant-ai-trader
git fetch origin
git reset --hard origin/cursor/quant-upgrade-a75f

# Paper boot + AutoCD every 10 min + daily data download at 01:00
.\scripts\windows_install_autostart.ps1 -Branch cursor/quant-upgrade-a75f -EnableDataDownload -DataDailyAt "01:00"

# Or data task only:
# .\scripts\install_lightsail_data_autostart.ps1 -DailyAt "01:00" -ForceDownload
```

**2) RTX 3060 PC (Admin PowerShell)**

```powershell
cd C:\Quant_Trader
git fetch origin
git reset --hard origin/cursor/quant-upgrade-a75f

.\scripts\bootstrap_local_gpu.ps1 -RepoRoot C:\Quant_Trader -DailyAt "03:00" -Epochs 40 -SkipRl
# or:
# .\scripts\install_local_train_autostart.ps1 -DailyAt "03:00" -Epochs 40 -SkipRl -WaitForDataMinutes 90
```

Keep the GPU PC **logged in** around 03:00. **Screen lock (Win+L) is fine** — the Interactive task still runs. **Sleep/hibernate** is the problem; the task uses `WakeToRun` + `StartWhenAvailable`. Also set Windows: *Settings → System → Power → Sleep → Never* (or only after the train window).

### Verify tasks

```powershell
Get-ScheduledTask -TaskName QAT-* | Format-Table TaskName, State
```

Logs:

- Lightsail: `C:\quant-ai-trader\logs\data-download-*.log`, `logs\cd-deploy.log`
- GPU: `C:\Quant_Trader\logs\gpu-train-*.log`

### Manual run (same scripts the tasks call)

```powershell
# Lightsail
.\scripts\lightsail_download_and_push.ps1 -ForceDownload

# GPU
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

## Verify on Lightsail

```powershell
Get-ChildItem C:\quant-ai-trader\data\models
Invoke-RestMethod http://127.0.0.1:8001/api/v2/infer/models/status -Headers @{ "X-API-Key"="dev-api-key-change-in-production" }
```
