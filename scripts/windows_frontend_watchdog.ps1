# Keep API gateway (+ optional :5180) alive so the UI stays reachable.
# ASCII-only. No here-strings. Safe string concat (no nested `" escapes).
# Children started via Win32_Process.Create to survive GHA orphan cleanup.
# Primary public UI: https://<host>/  (TLS proxy :8443 -> gateway :8001)
#   .\scripts\windows_frontend_watchdog.ps1 -InstallTask
#   .\scripts\windows_frontend_watchdog.ps1 -Once

param(
    [string]$RepoRoot = "C:\quant-ai-trader",
    [switch]$InstallTask,
    [switch]$Once
)

$ErrorActionPreference = "Continue"
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
             [System.Environment]::GetEnvironmentVariable("Path", "User")

if (-not (Test-Path $RepoRoot)) { throw "Missing $RepoRoot" }
Set-Location $RepoRoot
. (Join-Path $PSScriptRoot "windows_hidden_start.ps1")
$logDir = Join-Path $RepoRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir "frontend-watchdog.log"
$pidDir = Join-Path $RepoRoot "cache\windows_pids"
New-Item -ItemType Directory -Force -Path $pidDir | Out-Null

function Write-Log([string]$msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | $msg"
    Add-Content -Path $log -Value $line -ErrorAction SilentlyContinue
    Write-Host $line
}

function Test-Url([string]$Url) {
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 4
        return ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500)
    } catch { return $false }
}

function Get-Python {
    foreach ($cand in @(
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python311\python.exe",
        "python"
    )) {
        if ($cand -eq "python") {
            if (Get-Command python -ErrorAction SilentlyContinue) { return "python" }
        } elseif (Test-Path $cand) { return $cand }
    }
    return $null
}

function Start-DetachedBat([string]$BatPath, [string]$CommandMatch) {
    $pidVal = Start-QatHiddenBat -BatPath $BatPath -WorkingDirectory $RepoRoot -CommandMatch $CommandMatch
    if ($pidVal) {
        Write-Log ("hidden pid={0}" -f $pidVal)
        return $true
    }
    try {
        Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", $BatPath) -WorkingDirectory $RepoRoot -WindowStyle Hidden | Out-Null
        return $true
    } catch {
        Write-Log ("Start-Process fallback failed: {0}" -f $_.Exception.Message)
        return $false
    }
}

function Start-Gateway {
    $py = Get-Python
    if (-not $py) { Write-Log "python missing"; return }
    $bat = Join-Path $pidDir "start_api-gateway.bat"
    $outLog = Join-Path $logDir "api-gateway.out.log"
    $errLog = Join-Path $logDir "api-gateway.err.log"
    $runLine = '"{0}" -m uvicorn api_gateway.main:app --host 0.0.0.0 --port 8001 >> "{1}" 2>> "{2}"' -f $py, $outLog, $errLog
    $lines = @(
        "@echo off",
        ("set PYTHONPATH={0}" -f $RepoRoot),
        ("set QAT_PROJECT_ROOT={0}" -f $RepoRoot),
        ("cd /d {0}" -f $RepoRoot),
        $runLine
    )
    Set-Content -Path $bat -Value ($lines -join "`r`n") -Encoding ASCII
    Start-DetachedBat $bat "uvicorn api_gateway.main:app" | Out-Null
    Write-Log "started api-gateway :8001"
}

function Stop-TlsProxy {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object {
        $cl = $_.CommandLine
        if ($cl -and $cl -like "*windows_tls_proxy.py*") {
            try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } catch { }
            Write-Log ("stopped tls-proxy pid={0}" -f $_.ProcessId)
        }
    }
    foreach ($port in @(8443, 8081)) {
        $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        foreach ($c in $conns) {
            if ($c.OwningProcess -le 4) { continue }
            try { Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue } catch { }
            Write-Log ("freed port {0} pid={1}" -f $port, $c.OwningProcess)
        }
    }
    Start-Sleep -Seconds 1
}

function Start-TlsProxy {
    $py = Get-Python
    if (-not $py) { Write-Log "python missing"; return }
    $publicHost = $env:QAT_PUBLIC_HOST
    if (-not $publicHost) { $publicHost = "43.160.194.146" }
    $bat = Join-Path $pidDir "start_tls-proxy.bat"
    $outLog = Join-Path $logDir "tls-proxy.out.log"
    $errLog = Join-Path $logDir "tls-proxy.err.log"
    $runLine = '"{0}" scripts\windows_tls_proxy.py --ensure-cert --public-host {1} >> "{2}" 2>> "{3}"' -f $py, $publicHost, $outLog, $errLog
    $lines = @(
        "@echo off",
        ("set PYTHONPATH={0}" -f $RepoRoot),
        ("set QAT_PROJECT_ROOT={0}" -f $RepoRoot),
        ("set QAT_PUBLIC_HOST={0}" -f $publicHost),
        ("cd /d {0}" -f $RepoRoot),
        $runLine
    )
    Set-Content -Path $bat -Value ($lines -join "`r`n") -Encoding ASCII
    Start-DetachedBat $bat "windows_tls_proxy.py" | Out-Null
    Write-Log "started tls-proxy :8443/:8081"
}

function Test-Listen([int]$Port) {
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return [bool]$c
}

function Test-TlsProxy([string]$Mode) {
    $py = Get-Python
    if (-not $py) {
        Write-Log "python missing"
        return $false
    }
    & $py (Join-Path $RepoRoot "scripts\windows_tls_proxy.py") $Mode
    if ($LASTEXITCODE -eq 0) { return $true }
    Write-Log ("tls proxy {0} failed exit={1}" -f $Mode, $LASTEXITCODE)
    return $false
}

function Test-QatPortProxy([int]$ListenPort, [int]$ConnectPort) {
    $out = netsh interface portproxy show v4tov4 2>$null | Out-String
    $pattern = "0\.0\.0\.0\s+$ListenPort\s+127\.0\.0\.1\s+$ConnectPort"
    return ($out -match $pattern)
}

function Repair-QatPortProxy {
    param([int]$ListenPort, [int]$ConnectPort)
    if (Test-QatPortProxy -ListenPort $ListenPort -ConnectPort $ConnectPort) { return }
    Write-Log ("portproxy {0} is not 127.0.0.1:{1} - repairing" -f $ListenPort, $ConnectPort)
    netsh interface portproxy delete v4tov4 listenport=$ListenPort listenaddress=0.0.0.0 | Out-Null
    netsh interface portproxy add v4tov4 listenport=$ListenPort listenaddress=0.0.0.0 connectport=$ConnectPort connectaddress=127.0.0.1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Log ("portproxy {0} -> 127.0.0.1:{1}" -f $ListenPort, $ConnectPort)
    } else {
        Write-Log ("portproxy {0} repair failed" -f $ListenPort)
    }
}

function Start-Frontend5180 {
    $py = Get-Python
    if (-not $py) { return }
    $dist = Join-Path $RepoRoot "frontend\dist\index.html"
    if (-not (Test-Path $dist)) {
        Write-Log "frontend dist missing - use gateway SPA only"
        return
    }
    $bat = Join-Path $pidDir "start_frontend.bat"
    $outLog = Join-Path $logDir "frontend.out.log"
    $errLog = Join-Path $logDir "frontend.err.log"
    $runLine = '"{0}" scripts\windows_frontend_server.py --root "{1}" --port 5180 >> "{2}" 2>> "{3}"' -f $py, $RepoRoot, $outLog, $errLog
    $lines = @(
        "@echo off",
        ("set PYTHONPATH={0}" -f $RepoRoot),
        ("set QAT_PROJECT_ROOT={0}" -f $RepoRoot),
        ("cd /d {0}" -f $RepoRoot),
        $runLine
    )
    Set-Content -Path $bat -Value ($lines -join "`r`n") -Encoding ASCII
    Start-DetachedBat $bat "windows_frontend_server.py" | Out-Null
    Write-Log "started frontend :5180"
}

function Invoke-Check {
    $liveOk = Test-Url "http://127.0.0.1:8001/health/live"
    if (-not $liveOk) {
        $liveOk = Test-Url "http://127.0.0.1:8001/api/v2/status"
    }
    if (-not $liveOk) {
        Write-Log "gateway DOWN - restarting"
        Start-Gateway
        Start-Sleep -Seconds 5
    } else {
        Write-Log "gateway OK"
    }

    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8001/" -UseBasicParsing -TimeoutSec 5
        $ct = $r.Headers["Content-Type"]
        if ($r.StatusCode -eq 200 -and ($ct -match "html" -or $r.Content -match "<html")) {
            Write-Log "SPA OK on :8001"
        } else {
            Write-Log ("SPA unexpected status={0} content-type={1}" -f $r.StatusCode, $ct)
        }
    } catch {
        Write-Log ("SPA check failed: {0}" -f $_.Exception.Message)
    }

    if (-not (Test-Url "http://127.0.0.1:5180/")) {
        Write-Log "frontend :5180 down - restarting (optional)"
        Start-Frontend5180
    } else {
        Write-Log "frontend :5180 OK"
    }

    Repair-QatPortProxy -ListenPort 443 -ConnectPort 8443
    Repair-QatPortProxy -ListenPort 80 -ConnectPort 8081

    $listenOk = (Test-Listen 8443) -and (Test-Listen 8081)
    $handOk = $false
    if ($listenOk) {
        $handOk = Test-TlsProxy "--check-handshake"
    }
    if (-not $listenOk -or -not $handOk) {
        Write-Log "tls-proxy handshake failed - restarting"
        Stop-TlsProxy
        Start-TlsProxy
        Start-Sleep -Seconds 5
        if (Test-TlsProxy "--check-handshake") {
            Write-Log "tls-proxy handshake OK"
        } else {
            Write-Log "tls-proxy still failing after restart"
        }
    } else {
        Write-Log "tls-proxy OK"
    }
}

if ($InstallTask) {
    $wrapper = Join-Path $RepoRoot "scripts\_run_frontend_watchdog_logged.ps1"
    $watchdogPs1 = Join-Path $RepoRoot "scripts\windows_frontend_watchdog.ps1"
    $wrapperLines = @(
        '$ErrorActionPreference=''Continue''',
        ('Set-Location ''{0}''' -f $RepoRoot),
        ('powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{0}" -Once' -f $watchdogPs1)
    )
    Set-Content -Path $wrapper -Value ($wrapperLines -join "`r`n") -Encoding ASCII

    $arg = '-NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $wrapper
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory $RepoRoot
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $onceTrig = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
        -RepetitionInterval (New-TimeSpan -Minutes 2) `
        -RepetitionDuration ([TimeSpan]::FromDays(3650))
    $prin = New-ScheduledTaskPrincipal -UserId "Administrator" -RunLevel Highest -LogonType Interactive
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 0)
    Register-ScheduledTask -TaskName "QAT-Frontend-Watchdog" -Action $action `
        -Trigger @($trigger, $onceTrig) -Principal $prin -Settings $settings `
        -Description "QAT: keep gateway SPA, HTTPS proxy, and optional :5180 alive" -Force | Out-Null
    Write-Log "Registered QAT-Frontend-Watchdog"
    Invoke-Check
    exit 0
}

if ($Once) {
    Invoke-Check
    exit 0
}

while ($true) {
    Invoke-Check
    Start-Sleep -Seconds 120
}
