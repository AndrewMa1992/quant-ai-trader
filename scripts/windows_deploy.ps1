# Quant AI Trader - Windows Server paper deploy (ASCII-only for PS 5.1)
# DeployScriptVersion: 8
# Services start hidden (no cmd.exe popup per process). Logs: logs\*.log
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
Write-Host "  DeployScriptVersion: 8"
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
# Force paper Tiger account (do not leave live 20874631 as active in sim)
function Set-EnvLine([string]$Key, [string]$Value) {
    $lines = @(Get-Content ".env" -ErrorAction SilentlyContinue)
    $found = $false
    $out = foreach ($line in $lines) {
        if ($line -match ("^{0}=" -f [regex]::Escape($Key))) {
            $found = $true
            "{0}={1}" -f $Key, $Value
        } else { $line }
    }
    if (-not $found) { $out += ("{0}={1}" -f $Key, $Value) }
    # PS 5.1 -Encoding utf8 writes a BOM that can break python-dotenv
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllLines((Join-Path $Root ".env"), $out, $utf8)
}
Set-EnvLine "QAT_TIGER_ACCOUNT" "21837535188693626"
Set-EnvLine "QAT_EXEC_TIGER_ACCOUNT" "21837535188693626"
Set-EnvLine "QAT_TIGER_PAPER_TRADING" "true"
Set-EnvLine "QAT_TIGER_SANDBOX" "false"
if ($joined -notmatch '(?m)^QAT_TIGER_ID=') { Set-EnvLine "QAT_TIGER_ID" "20159337" }
$pemAbs = Join-Path $Root "certs\tiger_private_key.pem"
if (Test-Path $pemAbs) {
    Set-EnvLine "QAT_TIGER_PRIVATE_KEY_PATH" $pemAbs
}
if ($joined -notmatch '(?m)^QAT_TIGER_LICENSE=.+') { Set-EnvLine "QAT_TIGER_LICENSE" "TBSG" }

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

$GatewayPort = 8001
if ($env:QAT_API_PORT -match '^\d+$') { $GatewayPort = [int]$env:QAT_API_PORT }

if ($OpenFirewall) {
    $ports = @($GatewayPort, 8011, 8012, 8013, 8014, 8015, 8016, 5180)
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
        "python-dotenv>=1.0" "scikit-learn>=1.4" "joblib>=1.3" "yfinance>=0.2" `
        "tigeropen>=3.5.8"
    try {
        & $PythonExe -m pip install "torch" --index-url https://download.pytorch.org/whl/cpu
    } catch {
        Write-Host "[warn] torch install skipped"
    }
    Write-Host "[ok] Python packages ready"
}

# Always ensure tigeropen (CD uses -SkipInstall and previously never installed the SDK)
Write-Host "[..] ensuring tigeropen SDK..."
$tigeropenOk = $false
try {
    & $PythonExe -c "import tigeropen; print(getattr(tigeropen, '__version__', 'ok'))"
    if ($LASTEXITCODE -eq 0) { $tigeropenOk = $true }
} catch { }
if (-not $tigeropenOk) {
    Write-Host "[..] pip install tigeropen>=3.5.8"
    & $PythonExe -m pip install "tigeropen>=3.5.8"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[warn] tigeropen install failed - Tiger account will stay at zero until SDK is present"
    } else {
        Write-Host "[ok] tigeropen installed"
    }
} else {
    Write-Host "[ok] tigeropen present"
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

. (Join-Path $PSScriptRoot "windows_hidden_start.ps1")

function Start-QatService {
    param([string]$Name, [string]$Module, [int]$Port)
    $logOut = Join-Path $Root "logs\$Name.out.log"
    $logErr = Join-Path $Root "logs\$Name.err.log"
    $bat = Join-Path $pidDir "start_$Name.bat"
    $runLine = '"{0}" -m uvicorn {1} --host 0.0.0.0 --port {2} >> "{3}" 2>> "{4}"' -f $PythonExe, $Module, $Port, $logOut, $logErr
    $lines = @(
        "@echo off",
        ("set PYTHONPATH={0}" -f $Root),
        ("set QAT_PROJECT_ROOT={0}" -f $Root),
        ("set QAT_API_PORT={0}" -f $GatewayPort),
        ("set QAT_GATEWAY_URL=http://127.0.0.1:{0}" -f $GatewayPort),
        ("set QAT_TIGER_PRIVATE_KEY_PATH={0}" -f (Join-Path $Root "certs\tiger_private_key.pem")),
        ("cd /d {0}" -f $Root),
        $runLine
    )
    Set-Content -Path $bat -Value ($lines -join "`r`n") -Encoding ASCII
    $pidVal = Start-QatHiddenBat -BatPath $bat -WorkingDirectory $Root -CommandMatch ("uvicorn {0}" -f $Module)
    if (-not $pidVal) {
        $p = Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", $bat) `
            -WorkingDirectory $Root -PassThru -WindowStyle Hidden
        if ($p) { $pidVal = $p.Id }
    }
    Set-Content (Join-Path $pidDir "$Name.pid") $pidVal
    Write-Host ("[ok] {0,-16} :{1}  PID {2} (hidden)" -f $Name, $Port, $pidVal)
    Start-Sleep -Seconds 1
}

if ($GatewayPort -eq 80) {
    netsh interface portproxy delete v4tov4 listenport=80 listenaddress=0.0.0.0 | Out-Null
    Write-Host "[ok] Cleared portproxy on 80 so the gateway can bind it"
}
Write-Host "[..] starting backend services..."
Start-QatService "api-gateway"    "api_gateway.main:app"                  $GatewayPort
Start-QatService "data-service"    "services.data_service.main:app"         8011
Start-QatService "factor-service"  "services.factor_service.main:app"       8012
Start-QatService "model-train"     "services.model_train_service.main:app"  8013
Start-QatService "model-infer"     "services.model_infer_service.main:app"  8014
Start-QatService "risk-service"   "services.risk_service.main:app"         8015
Start-QatService "execution"       "services.execution_service.main:app"     8016

if (-not $SkipFrontend) {
    Write-Host "[..] frontend build..."
    Push-Location (Join-Path $Root "frontend")
    if (-not $SkipInstall) {
        & $NpmCmd install
    }
    $distIndex = Join-Path $Root "frontend\dist\index.html"
    $built = $false
    # CD uses -SkipInstall often - reuse dist to cut downtime (gateway serves SPA)
    if ((Test-Path $distIndex) -and $SkipInstall) {
        Write-Host "[ok] reuse existing frontend\dist (faster CD)"
        $built = $true
    }
    if (-not $built) {
        try {
            & $NpmCmd run build
            if (($LASTEXITCODE -eq 0) -and (Test-Path $distIndex)) { $built = $true }
        } catch {
            Write-Host "[warn] npm run build failed: $($_.Exception.Message)"
        }
    }
    if (-not $built) {
        Write-Host "[..] retry with npx vite build (skip vue-tsc)..."
        & $NpmCmd exec -- vite build
        if (($LASTEXITCODE -eq 0) -and (Test-Path $distIndex)) { $built = $true }
    }
    if (-not $built) {
        Write-Host "[ERR] frontend dist missing - UI will not start on :5180"
        if (Test-Path (Join-Path $Root "logs\frontend.err.log")) {
            Get-Content (Join-Path $Root "logs\frontend.err.log") -Tail 30
        }
    } else {
        $frontLogOut = Join-Path $Root "logs\frontend.out.log"
        $frontLogErr = Join-Path $Root "logs\frontend.err.log"
        $frontBat = Join-Path $pidDir "start_frontend.bat"
        $frontRun = '"{0}" scripts\windows_frontend_server.py --root "{1}" --port 5180 >> "{2}" 2>> "{3}"' -f $PythonExe, $Root, $frontLogOut, $frontLogErr
        $frontLines = @(
            "@echo off",
            ("cd /d {0}" -f $Root),
            $frontRun
        )
        Set-Content -Path $frontBat -Value ($frontLines -join "`r`n") -Encoding ASCII
        $frontPid = Start-QatHiddenBat -BatPath $frontBat -WorkingDirectory $Root -CommandMatch "windows_frontend_server.py"
        if (-not $frontPid) {
            $front = Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", $frontBat) `
                -WorkingDirectory $Root -PassThru -WindowStyle Hidden
            if ($front) { $frontPid = $front.Id }
        }
        Set-Content (Join-Path $pidDir "frontend.pid") $frontPid
        Write-Host "[ok] frontend        :5180  PID $frontPid (hidden)"
        Start-Sleep -Seconds 3
        try {
            $fr = Invoke-WebRequest -Uri "http://127.0.0.1:5180/" -UseBasicParsing -TimeoutSec 5
            Write-Host "[ok] frontend HTTP $($fr.StatusCode)"
        } catch {
            Write-Host "[warn] frontend not responding yet - see logs\frontend.err.log"
            if (Test-Path $frontLogErr) { Get-Content $frontLogErr -Tail 30 }
        }
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
    if (Test-LocalUrl "http://127.0.0.1:$GatewayPort/health") { $healthy = $true; break }
    Start-Sleep -Seconds 2
}
if ($healthy) {
    Write-Host "[ok] Gateway healthy  http://127.0.0.1:$GatewayPort/health"
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

# Easy public ports. Services stay on 8001 (API) and 5180 (frontend).
# 80  -> API gateway, 8080 -> frontend. Skip when the gateway itself binds 80.
if ($GatewayPort -ne 80) {
    netsh interface portproxy delete v4tov4 listenport=80 listenaddress=0.0.0.0 | Out-Null
    netsh interface portproxy add v4tov4 listenport=80 listenaddress=0.0.0.0 connectport=$GatewayPort connectaddress=127.0.0.1 | Out-Null
    netsh interface portproxy delete v4tov4 listenport=8080 listenaddress=0.0.0.0 | Out-Null
    netsh interface portproxy add v4tov4 listenport=8080 listenaddress=0.0.0.0 connectport=5180 connectaddress=127.0.0.1 | Out-Null
    netsh advfirewall firewall delete rule name="QAT-HTTP-80" | Out-Null
    netsh advfirewall firewall add rule name="QAT-HTTP-80" dir=in action=allow protocol=TCP localport=80 | Out-Null
    netsh advfirewall firewall delete rule name="QAT-HTTP-8080" | Out-Null
    netsh advfirewall firewall add rule name="QAT-HTTP-8080" dir=in action=allow protocol=TCP localport=8080 | Out-Null
    Write-Host "[ok] Public forward 80 -> $GatewayPort and 8080 -> 5180"
}

Write-Host ""
Write-Host "============================================"
Write-Host "  Deployed (PAPER mode)"
Write-Host "  API:      http://127.0.0.1:$GatewayPort/health"
Write-Host "  Frontend: http://127.0.0.1:5180  (optional local UI)"
Write-Host "  Public API:      http://<host>/           (port 80 -> $GatewayPort)"
Write-Host "  Public frontend: http://<host>:8080/      (port 8080 -> 5180)"
Write-Host "  If UI shows 502: gateway is down - check logs above"
Write-Host "  Stop:     .\scripts\windows_stop.ps1"
Write-Host "============================================"
