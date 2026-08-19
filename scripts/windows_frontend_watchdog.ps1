# Keep API gateway (+ optional :5180) alive so the UI stays reachable.
# Primary public UI: http://<host>:8001/  (gateway SPA)
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
$logDir = Join-Path $RepoRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir "frontend-watchdog.log"
$pidDir = Join-Path $RepoRoot "cache\windows_pids"
New-Item -ItemType Directory -Force -Path $pidDir | Out-Null

function Write-Log([string]$msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | $msg"
    Add-Content -Path $log -Value $line
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

function Start-Gateway {
    $py = Get-Python
    if (-not $py) { Write-Log "python missing"; return }
    $bat = Join-Path $pidDir "start_api-gateway.bat"
    $batBody = @"
@echo off
set PYTHONPATH=$RepoRoot
set QAT_PROJECT_ROOT=$RepoRoot
cd /d "$RepoRoot"
"$py" -m uvicorn api_gateway.main:app --host 0.0.0.0 --port 8001
"@
    Set-Content -Path $bat -Value $batBody -Encoding ASCII
    Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", "`"$bat`"") `
        -WorkingDirectory $RepoRoot -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDir "api-gateway.out.log") `
        -RedirectStandardError (Join-Path $logDir "api-gateway.err.log")
    Write-Log "started api-gateway :8001"
}

function Start-Frontend5180 {
    $py = Get-Python
    if (-not $py) { return }
    $dist = Join-Path $RepoRoot "frontend\dist\index.html"
    if (-not (Test-Path $dist)) {
        Write-Log "frontend dist missing — use gateway SPA only"
        return
    }
    $bat = Join-Path $pidDir "start_frontend.bat"
    $batBody = @"
@echo off
set PYTHONPATH=$RepoRoot
set QAT_PROJECT_ROOT=$RepoRoot
cd /d "$RepoRoot"
"$py" scripts\windows_frontend_server.py --root "$RepoRoot" --port 5180
"@
    Set-Content -Path $bat -Value $batBody -Encoding ASCII
    Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", "`"$bat`"") `
        -WorkingDirectory $RepoRoot -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDir "frontend.out.log") `
        -RedirectStandardError (Join-Path $logDir "frontend.err.log")
    Write-Log "started frontend :5180"
}

function Invoke-Check {
    # Prefer fast liveness endpoint
    $liveOk = Test-Url "http://127.0.0.1:8001/health/live"
    if (-not $liveOk) {
        $liveOk = Test-Url "http://127.0.0.1:8001/api/v2/status"
    }
    if (-not $liveOk) {
        Write-Log "gateway DOWN — restarting"
        Start-Gateway
        Start-Sleep -Seconds 5
    } else {
        Write-Log "gateway OK"
    }

    # SPA must return HTML (not 401)
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
        Write-Log "frontend :5180 down — restarting (optional)"
        Start-Frontend5180
    } else {
        Write-Log "frontend :5180 OK"
    }
}

if ($InstallTask) {
    $wrapper = Join-Path $RepoRoot "scripts\_run_frontend_watchdog_logged.ps1"
    $body = @"
`$ErrorActionPreference='Continue'
Set-Location '$RepoRoot'
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path '$RepoRoot' 'scripts\windows_frontend_watchdog.ps1') -Once
"@
    Set-Content -Path $wrapper -Value $body -Encoding UTF8
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$wrapper`"" `
        -WorkingDirectory $RepoRoot
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $onceTrig = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
        -RepetitionInterval (New-TimeSpan -Minutes 2) `
        -RepetitionDuration ([TimeSpan]::FromDays(3650))
    $prin = New-ScheduledTaskPrincipal -UserId "Administrator" -RunLevel Highest -LogonType Interactive
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 0)
    Register-ScheduledTask -TaskName "QAT-Frontend-Watchdog" -Action $action `
        -Trigger @($trigger, $onceTrig) -Principal $prin -Settings $settings `
        -Description "QAT: keep gateway SPA (:8001) and optional :5180 alive" -Force | Out-Null
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
