# Quant AI Trader - Windows Server paper deploy (ASCII-only for PS 5.1)
# DeployScriptVersion: 4
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
Write-Host "  DeployScriptVersion: 4"
Write-Host "  Root: $Root"
Write-Host "============================================"

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
    # Launcher bat ensures PYTHONPATH is set even if Start-Process env is odd
    $bat = Join-Path $pidDir "start_$Name.bat"
    $batBody = @"
@echo off
set PYTHONPATH=$Root
set QAT_PROJECT_ROOT=$Root
cd /d "$Root"
"$PythonExe" -m uvicorn $Module --host 0.0.0.0 --port $Port
"@
    Set-Content -Path $bat -Value $batBody -Encoding ASCII
    $p = Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", "`"$bat`"") `
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
    $frontLogOut = Join-Path $Root "logs\frontend.out.log"
    $frontLogErr = Join-Path $Root "logs\frontend.err.log"
    $frontBat = Join-Path $pidDir "start_frontend.bat"
    try {
        & $NpmCmd run build
        if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
        $batBody = @"
@echo off
cd /d "$Root\frontend"
"$NpmCmd" run preview -- --host 0.0.0.0 --port 5180
"@
        Set-Content -Path $frontBat -Value $batBody -Encoding ASCII
        $front = Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", "`"$frontBat`"") `
            -WorkingDirectory (Join-Path $Root "frontend") -PassThru -WindowStyle Hidden `
            -RedirectStandardOutput $frontLogOut -RedirectStandardError $frontLogErr
        $frontStarted = $true
    } catch {
        Write-Host "[warn] build/preview failed, falling back to vite dev: $($_.Exception.Message)"
        $batBody = @"
@echo off
cd /d "$Root\frontend"
"$NpmCmd" run dev -- --host 0.0.0.0 --port 5180
"@
        Set-Content -Path $frontBat -Value $batBody -Encoding ASCII
        $front = Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", "`"$frontBat`"") `
            -WorkingDirectory (Join-Path $Root "frontend") -PassThru -WindowStyle Hidden `
            -RedirectStandardOutput $frontLogOut -RedirectStandardError $frontLogErr
        $frontStarted = $true
    }
    if ($frontStarted) {
        Set-Content (Join-Path $pidDir "frontend.pid") $front.Id
        Write-Host "[ok] frontend        :5180  PID $($front.Id)"
    }
    Pop-Location
}

function Test-LocalUrl([string]$Url) {
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
        return ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500)
    } catch {
        return $false
    }
}

Write-Host "[..] waiting for gateway health..."
$healthy = $false
for ($i = 0; $i -lt 45; $i++) {
    if (Test-LocalUrl "http://127.0.0.1:8001/health") { $healthy = $true; break }
    Start-Sleep -Seconds 2
}
if ($healthy) {
    Write-Host "[ok] Gateway healthy  http://127.0.0.1:8001/health"
} else {
    Write-Host "[ERR] Gateway NOT healthy - API calls from UI will be 502"
    $errLog = Join-Path $Root "logs\api-gateway.err.log"
    if (Test-Path $errLog) {
        Write-Host "---- logs\api-gateway.err.log (tail) ----"
        Get-Content $errLog -Tail 40
        Write-Host "-----------------------------------------"
    }
}

Write-Host "[..] checking microservice ports..."
$svcPorts = @{
    "data-service" = 8011
    "factor-service" = 8012
    "model-train" = 8013
    "model-infer" = 8014
    "risk-service" = 8015
    "execution" = 8016
}
foreach ($name in $svcPorts.Keys) {
    $port = $svcPorts[$name]
    if (Test-LocalUrl "http://127.0.0.1:$port/health") {
        Write-Host "[ok] $name :$port"
    } else {
        Write-Host "[warn] $name :$port not healthy - see logs\$name.err.log"
    }
}

if (-not $SkipFrontend) {
    Start-Sleep -Seconds 3
    if (Test-LocalUrl "http://127.0.0.1:5180/") {
        Write-Host "[ok] Frontend listening :5180"
    } else {
        Write-Host "[warn] Frontend :5180 not responding - see logs\frontend.err.log"
    }
}

Write-Host ""
Write-Host "============================================"
Write-Host "  Deployed (PAPER mode)"
Write-Host "  API:      http://127.0.0.1:8001/health"
Write-Host "  Frontend: http://127.0.0.1:5180"
Write-Host "  Public:   http://3.106.139.233:5180"
Write-Host "  If UI shows 502: gateway is down - check logs above"
Write-Host "  Stop:     .\scripts\windows_stop.ps1"
Write-Host "============================================"
