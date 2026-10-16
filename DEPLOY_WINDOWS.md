# Windows Server / Lightsail Deployment Guide (Native Paper Mode)

Applies to: Amazon Lightsail **Windows Server 2022** (for example `Windows_Server_2022-1`, public IP `3.106.139.233`).

> Lightsail Windows typically **does not support nested virtualization**, so Docker Linux containers are difficult to run.  
> This guide uses **native Python + Node processes** and does not depend on Docker.

---

## 0. Sign in with RDP (not SSH)

1. Open the Lightsail console → Instances → `Windows_Server_2022-1`
2. Click **Connect using RDP** (browser), or connect from your local machine with `mstsc` to `3.106.139.233:3389`
3. Username: `Administrator`  
   Password: obtain the **Default password** on the Connect page

### Lightsail Networking — open ports

Networking → IPv4 Firewall — add inbound rules:

| Port | Purpose |
|------|------|
| 3389 | RDP |
| 8001 | API Gateway |
| 5180 | Frontend |

---

## 1. Install dependencies (first time)

On the RDP desktop, open **PowerShell (Administrator)**:

```powershell
# Git
winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements

# Python 3.12
winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements

# Node.js 20 LTS (frontend)
winget install --id OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements
```

Close and reopen PowerShell, then confirm:

```powershell
python --version
git --version
node --version
npm --version
```

---

## 2. Sync the code (the only side branch)

Newly opened PowerShell sessions often cannot find the newly installed `git` (PATH has not been refreshed). Run this first:

```powershell
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
cd C:\quant-ai-trader
```

If `git` is still not found, use the full path:

```powershell
& "C:\Program Files\Git\cmd\git.exe" fetch origin
& "C:\Program Files\Git\cmd\git.exe" checkout cursor/quant-upgrade-a75f
& "C:\Program Files\Git\cmd\git.exe" reset --hard origin/cursor/quant-upgrade-a75f
```

Or (after pulling Version 4) use the repository script:

```powershell
.\scripts\windows_sync.ps1
```

Confirm the script is the new version (it should show `DeployScriptVersion: 4`):

```powershell
Get-Content .\scripts\windows_deploy.ps1 -TotalCount 3
```

If it is still Version 3 / you see `string is missing the terminator`, the sync has not succeeded — do not deploy yet.

### 502 Bad Gateway on the page

The frontend on `:5180` reverse-proxies `/api` to `127.0.0.1:8001`. A 502 almost always means **the gateway is not running**. Check on the server:

```powershell
Invoke-WebRequest http://127.0.0.1:8001/health -UseBasicParsing
Get-Content C:\quant-ai-trader\logs\api-gateway.err.log -Tail 50
```

For private repositories, use a PAT or configure a GitHub SSH key.

Later updates:

```powershell
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
cd C:\quant-ai-trader
.\scripts\windows_sync.ps1
.\scripts\windows_stop.ps1
.\scripts\windows_deploy.ps1 -OpenFirewall
```

---

## 3. One-click start

```powershell
cd C:\quant-ai-trader
Set-ExecutionPolicy -Scope Process Bypass -Force
.\scripts\windows_deploy.ps1 -OpenFirewall
```

Parameter descriptions:

| Parameter | Effect |
|------|------|
| `-OpenFirewall` | Open Windows Firewall for 80/443/8001/5180 and related ports (requires Administrator) |
| `-SkipInstall` | Skip pip/npm install (subsequent starts) |
| `-SkipFrontend` | Start backend only |

---

## 4. Access

Inside the local RDP session:

- API: http://127.0.0.1:8001/health  
- Frontend: http://127.0.0.1:5180  

From an external browser the Windows host serves the dashboard on HTTPS. Port 443 terminates TLS in `scripts/windows_tls_proxy.py` and forwards to the gateway. Port 80 answers with a redirect to HTTPS. A bare IP uses a self-signed certificate generated on the server under `certs\tls\` (browsers warn until you continue). Internal checks stay on `http://127.0.0.1:8001/health`.

The optional Lightsail UI, when used, is still:

- http://3.106.139.233:5180  
- http://3.106.139.233:8001/health  

Default is **paper / simulated trading**; live orders are not placed.

---

## 5. Stop / view logs

```powershell
.\scripts\windows_stop.ps1
Get-Content C:\quant-ai-trader\logs\api-gateway.err.log -Tail 80
```

PID files: `cache\windows_pids\`

---

## 6. Autostart + auto-deploy (recommended)

Use **Windows Task Scheduler** (does not depend on the GitHub Runner service; more stable):

1. **Start paper services automatically on boot**
2. **Every 10 minutes**, check GitHub: if there is a new commit or a service is down → automatically pull + restart

### 6.1 One-time install (Administrator PowerShell)

```powershell
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
cd C:\quant-ai-trader
& "C:\Program Files\Git\cmd\git.exe" fetch origin
& "C:\Program Files\Git\cmd\git.exe" reset --hard origin/cursor/quant-upgrade-a75f

Set-ExecutionPolicy -Scope Process Bypass -Force
# Deploy once immediately, and register boot + scheduled auto-deploy
.\scripts\windows_install_autostart.ps1 -Branch cursor/quant-upgrade-a75f -RunNow
```

After merging into `main`, change the tracked branch to main:

```powershell
.\scripts\windows_install_autostart.ps1 -Branch main -RunNow
```

View tasks: `taskschd.msc` → `QAT-Paper-Boot` / `QAT-Paper-AutoCD`  
Logs: `C:\quant-ai-trader\logs\cd-deploy.log`

### 6.2 Day-to-day development

1. Change code → PR → CI
2. Merge into the tracked branch (currently `cursor/quant-upgrade-a75f`; use `main` once stable)
3. The server automatically pulls and restarts within about 10 minutes
4. Verify: http://3.106.139.233:8001/health and http://3.106.139.233:5180

### 6.3 Optional: GitHub Actions Runner

Task Scheduler is sufficient for auto-deploy and auto-run. If you still want Actions:

1. Copy the token from https://github.com/AndrewMa1992/quant-ai-trader/settings/actions/runners/new
2. `.\scripts\windows_install_runner.ps1 -Token "..."` (requires `--runasservice` to get svc.cmd)
3. Or `cd C:\actions-runner` then `cmd /c "run.cmd"` to stay online

---

## Troubleshooting

| Symptom | Action |
|------|------|
| `python` not found | Reopen the terminal; or use `py -3.12` |
| 5180 not reachable from the internet | Lightsail Firewall + `-OpenFirewall` |
| Blank frontend | `cd frontend; npm install; npm run build` |
| Gateway 503 | Wait 30s; check `logs\*.err.log` |
| Redis errors | Can be ignored (Redis is optional on Windows by default) |
| pip is slow | Switch to the Tsinghua PyPI mirror: `pip install -i https://pypi.tuna.tsinghua.edu.cn/simple ...` |

---

## Sizing recommendation

Lightsail Windows: recommend **≥ 4 GB RAM**; the first `pip`/`npm` install uses significant disk space.
