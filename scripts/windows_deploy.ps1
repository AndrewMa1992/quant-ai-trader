# Quant AI Trader – Windows Server one-click paper deploy (Lightsail-friendly)
# Usage (PowerShell as Administrator recommended once for firewall):
#   Set-ExecutionPolicy -Scope Process Bypass -Force
#   .\scripts\windows_deploy.ps1
#
# Stops with: .\scripts\windows_stop.ps1

[CmdletBinding()]
param(
    [switch]$SkipFrontend,
    [switch]$SkipInstall,
    [switch]$OpenFirewall
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Quant AI Trader – Windows Paper Deploy" -ForegroundColor Cyan
Write-Host "  Root: $Root" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

function Assert-Command($Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name. Install it first (see DEPLOY_WINDOWS.md)."
    }
}

# ── Prerequisites ───────────────────────────────────────────
Assert-Command python
Assert-Command pip
$pyVer = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Host "[ok] Python $pyVer"
if ([version]$pyVer -lt [version]"3.11") {
    throw "Python 3.11+ required (found $pyVer)"
}

# ── Env ──────────────────────────────────────────────────────
if (-not (Test-Path ".env")) {
    Copy-Item ".env.windows" ".env"
    Write-Host "[ok] Created .env from .env.windows"
} else {
    Write-Host "[ok] Using existing .env"
}

# Force paper lock
$envText = Get-Content ".env" -Raw
if ($envText -notmatch '(?m)^QAT_EXECUTION_MODE=paper') {
    Add-Content ".env" "`nQAT_EXECUTION_MODE=paper"
}
if ($envText -notmatch '(?m)^QAT_TRADING_SIMULATION_MODE=true') {
    Add-Content ".env" "`nQAT_TRADING_SIMULATION_MODE=true"
}
if ($envText -notmatch '(?m)^QAT_USE_DOCKER=false') {
    Add-Content ".env" "`nQAT_USE_DOCKER=false"
}

New-Item -ItemType Directory -Force -Path "data","data\daily","data\models","cache","logs","frontend\dist" | Out-Null

# Load .env into process
Get-Content ".env" | ForEach-Object {
    if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
    $pair = $_.Split('=', 2)
    if ($pair.Count -eq 2) {
        [Environment]::SetEnvironmentVariable($pair[0].Trim(), $pair[1].Trim(), "Process")
    }
}
$env:PYTHONPATH = $Root
$env:QAT_PROJECT_ROOT = $Root

# ── Firewall (optional, needs Admin) ───────────────────────
if ($OpenFirewall) {
    $ports = @(8001, 8011, 8012, 8013, 8014, 8015, 8016, 5180)
    foreach ($p in $ports) {
        $rule = "QAT-Port-$p"
        if (-not (Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue)) {
            New-NetFirewallRule -DisplayName $rule -Direction Inbound -Protocol TCP -LocalPort $p -Action Allow | Out-Null
            Write-Host "[ok] Firewall opened TCP $p"
        }
    }
}

# ── Python deps ─────────────────────────────────────────────
if (-not $SkipInstall) {
    Write-Host "[..] pip install (core runtime)…"
    & python -m pip install -U pip setuptools wheel
    # Lightweight core first so API can boot even if heavy ML wheels fail
    & python -m pip install `
        "fastapi>=0.110" "uvicorn[standard]>=0.27" "websockets>=12" `
        "numpy>=1.26" "pandas>=2.2" "scipy>=1.12" "pyarrow>=15" `
        "aiosqlite>=0.20" "sqlalchemy[asyncio]>=2.0" "alembic>=1.13" `
        "redis>=5.0" "httpx>=0.27" "loguru>=0.7" "pydantic>=2" "pydantic-settings>=2" `
        "python-dotenv>=1.0" "scikit-learn>=1.4" "joblib>=1.3" "yfinance>=0.2"
    try {
        & python -m pip install "torch" --index-url https://download.pytorch.org/whl/cpu
    } catch {
        Write-Host "[warn] torch install skipped: $_" -ForegroundColor Yellow
    }
    try {
        & python -m pip install -e ".[dev]" 2>$null
    } catch {
        Write-Host "[warn] editable install skipped (optional)" -ForegroundColor Yellow
    }
    Write-Host "[ok] Python packages ready"
}

# ── Frontend ────────────────────────────────────────────────
$hasNode = [bool](Get-Command npm -ErrorAction SilentlyContinue)
if (-not $SkipFrontend) {
    if (-not $hasNode) {
        Write-Host "[warn] npm not found — skipping frontend. Install Node 18+ LTS." -ForegroundColor Yellow
        $SkipFrontend = $true
    }
}

# ── Stop previous instance ─────────────────────────────────
if (Test-Path "scripts\windows_stop.ps1") {
    try { & powershell -ExecutionPolicy Bypass -File "scripts\windows_stop.ps1" } catch { }
}

$pidDir = Join-Path $Root "cache\windows_pids"
New-Item -ItemType Directory -Force -Path $pidDir | Out-Null
Get-ChildItem $pidDir -Filter "*.pid" -ErrorAction SilentlyContinue | Remove-Item -Force

function Start-QatService {
    param([string]$Name, [string]$Module, [int]$Port)
    $logOut = Join-Path $Root "logs\$Name.out.log"
    $logErr = Join-Path $Root "logs\$Name.err.log"
    $args = @("-m", "uvicorn", $Module, "--host", "0.0.0.0", "--port", "$Port")
    $p = Start-Process -FilePath "python" -ArgumentList $args `
        -WorkingDirectory $Root -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $logOut -RedirectStandardError $logErr
    Set-Content (Join-Path $pidDir "$Name.pid") $p.Id
    Write-Host ("[ok] {0,-16} :{1}  PID {2}" -f $Name, $Port, $p.Id)
    Start-Sleep -Seconds 2
}

Write-Host "[..] starting backend services…"
Start-QatService "api-gateway"   "api_gateway.main:app"                 8001
Start-QatService "data-service"   "services.data_service.main:app"        8011
Start-QatService "factor-service" "services.factor_service.main:app"      8012
Start-QatService "model-train"    "services.model_train_service.main:app"  8013
Start-QatService "model-infer"    "services.model_infer_service.main:app" 8014
Start-QatService "risk-service"   "services.risk_service.main:app"        8015
Start-QatService "execution"      "services.execution_service.main:app"    8016

if (-not $SkipFrontend) {
    Write-Host "[..] frontend npm install + build/dev…"
    Push-Location (Join-Path $Root "frontend")
    if (-not $SkipInstall) {
        & npm install
    }
    # Prefer production build + static serve if vite preview available
    try {
        & npm run build
        $front = Start-Process -FilePath "npm" -ArgumentList @("run", "preview", "--", "--host", "0.0.0.0", "--port", "5180") `
            -WorkingDirectory (Join-Path $Root "frontend") -PassThru -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $Root "logs\frontend.out.log") `
            -RedirectStandardError (Join-Path $Root "logs\frontend.err.log")
    } catch {
        $front = Start-Process -FilePath "npm" -ArgumentList @("run", "dev", "--", "--host", "0.0.0.0", "--port", "5180") `
            -WorkingDirectory (Join-Path $Root "frontend") -PassThru -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $Root "logs\frontend.out.log") `
            -RedirectStandardError (Join-Path $Root "logs\frontend.err.log")
    }
    Set-Content (Join-Path $pidDir "frontend.pid") $front.Id
    Pop-Location
    Write-Host "[ok] frontend        :5180  PID $($front.Id)"
}

Write-Host "[..] waiting for gateway health…"
$healthy = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8001/health" -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $healthy = $true; break }
    } catch { Start-Sleep -Seconds 2 }
}
if ($healthy) {
    Write-Host "[ok] Gateway healthy" -ForegroundColor Green
} else {
    Write-Host "[warn] Gateway not healthy yet — check logs\api-gateway.err.log" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Deployed (PAPER mode)" -ForegroundColor Green
Write-Host "  API:      http://127.0.0.1:8001" -ForegroundColor Green
Write-Host "  Frontend: http://127.0.0.1:5180" -ForegroundColor Green
Write-Host "  Public:   http://3.106.139.233:5180" -ForegroundColor Green
Write-Host "  Stop:     .\scripts\windows_stop.ps1" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
