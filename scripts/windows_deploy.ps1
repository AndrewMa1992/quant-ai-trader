# Quant AI Trader - Windows Server paper deploy (ASCII-only for PS 5.1)
# Usage:
#   Set-ExecutionPolicy -Scope Process Bypass -Force
#   .\scripts\windows_deploy.ps1 -OpenFirewall
# Stop:
#   .\scripts\windows_stop.ps1

[CmdletBinding()]
param(
    [switch]$SkipFrontend,
    [switch]$SkipInstall,
    [switch]$OpenFirewall
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

# Refresh PATH so git/python/node work in this session
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
             [System.Environment]::GetEnvironmentVariable("Path", "User")

Write-Host "============================================"
Write-Host "  Quant AI Trader - Windows Paper Deploy"
Write-Host "  Root: $Root"
Write-Host "============================================"

function Assert-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name. See DEPLOY_WINDOWS.md"
    }
}

# Prefer full paths if PATH still broken
$PythonExe = $null
foreach ($cand in @(
    "python",
    "C:\Program Files\Python312\python.exe",
    "C:\Program Files\Python311\python.exe",
    "$env:LocalAppData\Programs\Python\Python312\python.exe"
)) {
    if ($cand -eq "python") {
        if (Get-Command python -ErrorAction SilentlyContinue) { $PythonExe = "python"; break }
    } elseif (Test-Path $cand) {
        $PythonExe = $cand
        break
    }
}
if (-not $PythonExe) { throw "Python not found. Install Python 3.12 and reopen PowerShell." }

$NpmCmd = $null
foreach ($cand in @(
    "npm",
    "C:\Program Files\nodejs\npm.cmd"
)) {
    if ($cand -eq "npm") {
        if (Get-Command npm -ErrorAction SilentlyContinue) { $NpmCmd = "npm"; break }
    } elseif (Test-Path $cand) {
        $NpmCmd = $cand
        break
    }
}

Write-Host "[ok] Python: $PythonExe"
if ($NpmCmd) { Write-Host "[ok] npm: $NpmCmd" } else { Write-Host "[warn] npm not found" }

# Env file
if (-not (Test-Path ".env")) {
    Copy-Item ".env.windows" ".env"
    Write-Host "[ok] Created .env from .env.windows"
} else {
    Write-Host "[ok] Using existing .env"
}

$envLines = Get-Content ".env"
$joined = ($envLines -join "`n")
if ($joined -notmatch '(?m)^QAT_EXECUTION_MODE=paper') { Add-Content ".env" "QAT_EXECUTION_MODE=paper" }
if ($joined -notmatch '(?m)^QAT_TRADING_SIMULATION_MODE=true') { Add-Content ".env" "QAT_TRADING_SIMULATION_MODE=true" }
if ($joined -notmatch '(?m)^QAT_USE_DOCKER=false') { Add-Content ".env" "QAT_USE_DOCKER=false" }

New-Item -ItemType Directory -Force -Path "data", "data\daily", "data\models", "cache", "logs" | Out-Null

Get-Content ".env" | ForEach-Object {
    if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
    $pair = $_.Split("=", 2)
    if ($pair.Count -eq 2) {
        [Environment]::SetEnvironmentVariable($pair[0].Trim(), $pair[1].Trim(), "Process")
    }
}
$env:PYTHONPATH = $Root
$env:QAT_PROJECT_ROOT = $Root

if ($OpenFirewall) {
    $ports = @(8001, 8011, 8012, 8013, 8014, 8015, 8016, 5180)
    foreach ($p in $ports) {
        $rule = "QAT-Port-$p"
        if (-not (Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue)) {
            try {
                New-NetFirewallRule -DisplayName $rule -Direction Inbound -Protocol TCP -LocalPort $p -Action Allow | Out-Null
                Write-Host "[ok] Firewall opened TCP $p"
            } catch {
                Write-Host "[warn] Could not open firewall port $p (run as Admin)"
            }
        }
    }
}

if (-not $SkipInstall) {
    Write-Host "[..] pip install core packages..."
    & $PythonExe -m pip install -U pip setuptools wheel
    & $PythonExe -m pip install `
        "fastapi>=0.110" "uvicorn[standard]>=0.27" "websockets>=12" `
        "numpy>=1.26" "pandas>=2.2" "scipy>=1.12" "pyarrow>=15" `
        "aiosqlite>=0.20" "sqlalchemy[asyncio]>=2.0" "alembic>=1.13" `
        "redis>=5.0" "httpx>=0.27" "loguru>=0.7" "pydantic>=2" "pydantic-settings>=2" `
        "python-dotenv>=1.0" "scikit-learn>=1.4" "joblib>=1.3" "yfinance>=0.2"
    try {
        & $PythonExe -m pip install "torch" --index-url https://download.pytorch.org/whl/cpu
    } catch {
        Write-Host "[warn] torch install skipped"
    }
    Write-Host "[ok] Python packages ready"
}

$hasNode = $false
if ($NpmCmd) { $hasNode = $true }
if (-not $SkipFrontend) {
    if (-not $hasNode) {
        Write-Host "[warn] npm not found - skipping frontend"
        $SkipFrontend = $true
    }
}

if (Test-Path "scripts\windows_stop.ps1") {
    try {
        & powershell -ExecutionPolicy Bypass -File "scripts\windows_stop.ps1"
    } catch { }
}

$pidDir = Join-Path $Root "cache\windows_pids"
New-Item -ItemType Directory -Force -Path $pidDir | Out-Null
Get-ChildItem $pidDir -Filter "*.pid" -ErrorAction SilentlyContinue | Remove-Item -Force

function Start-QatService {
    param([string]$Name, [string]$Module, [int]$Port)
    $logOut = Join-Path $Root "logs\$Name.out.log"
    $logErr = Join-Path $Root "logs\$Name.err.log"
    $argList = @("-m", "uvicorn", $Module, "--host", "0.0.0.0", "--port", "$Port")
    $p = Start-Process -FilePath $PythonExe -ArgumentList $argList `
        -WorkingDirectory $Root -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $logOut -RedirectStandardError $logErr
    Set-Content (Join-Path $pidDir "$Name.pid") $p.Id
    Write-Host ("[ok] {0,-16} :{1}  PID {2}" -f $Name, $Port, $p.Id)
    Start-Sleep -Seconds 2
}

Write-Host "[..] starting backend services..."
Start-QatService "api-gateway"    "api_gateway.main:app"                  8001
Start-QatService "data-service"    "services.data_service.main:app"         8011
Start-QatService "factor-service"  "services.factor_service.main:app"       8012
Start-QatService "model-train"     "services.model_train_service.main:app"  8013
Start-QatService "model-infer"     "services.model_infer_service.main:app"  8014
Start-QatService "risk-service"   "services.risk_service.main:app"         8015
Start-QatService "execution"       "services.execution_service.main:app"     8016

if (-not $SkipFrontend) {
    Write-Host "[..] frontend npm install + build..."
    Push-Location (Join-Path $Root "frontend")
    if (-not $SkipInstall) {
        & $NpmCmd install
    }
    $frontStarted = $false
    try {
        & $NpmCmd run build
        $front = Start-Process -FilePath $NpmCmd -ArgumentList @("run", "preview", "--", "--host", "0.0.0.0", "--port", "5180") `
            -WorkingDirectory (Join-Path $Root "frontend") -PassThru -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $Root "logs\frontend.out.log") `
            -RedirectStandardError (Join-Path $Root "logs\frontend.err.log")
        $frontStarted = $true
    } catch {
        $front = Start-Process -FilePath $NpmCmd -ArgumentList @("run", "dev", "--", "--host", "0.0.0.0", "--port", "5180") `
            -WorkingDirectory (Join-Path $Root "frontend") -PassThru -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $Root "logs\frontend.out.log") `
            -RedirectStandardError (Join-Path $Root "logs\frontend.err.log")
        $frontStarted = $true
    }
    if ($frontStarted) {
        Set-Content (Join-Path $pidDir "frontend.pid") $front.Id
        Write-Host "[ok] frontend        :5180  PID $($front.Id)"
    }
    Pop-Location
}

Write-Host "[..] waiting for gateway health..."
$healthy = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8001/health" -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $healthy = $true; break }
    } catch {
        Start-Sleep -Seconds 2
    }
}
if ($healthy) {
    Write-Host "[ok] Gateway healthy"
} else {
    Write-Host "[warn] Gateway not healthy yet - check logs\api-gateway.err.log"
}

Write-Host ""
Write-Host "============================================"
Write-Host "  Deployed (PAPER mode)"
Write-Host "  API:      http://127.0.0.1:8001"
Write-Host "  Frontend: http://127.0.0.1:5180"
Write-Host "  Public:   http://3.106.139.233:5180"
Write-Host "  Stop:     .\scripts\windows_stop.ps1"
Write-Host "============================================"
