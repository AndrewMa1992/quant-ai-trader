# Keep trading_pipeline.py alive on Lightsail Windows (paper / Tiger sim).
# ASCII-only. No here-strings. Safe string concat (no nested `" escapes).
# Children started via Win32_Process.Create to survive GHA orphan cleanup.
#   .\scripts\windows_pipeline_watchdog.ps1 -InstallTask
#   .\scripts\windows_pipeline_watchdog.ps1 -Once

param(
    [string]$RepoRoot = "C:\quant-ai-trader",
    [string]$Branch = "main",
    [int]$IntervalSeconds = 120,
    [switch]$InstallTask,
    [switch]$Once
)

$ErrorActionPreference = "Continue"
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
             [System.Environment]::GetEnvironmentVariable("Path", "User")

if (-not (Test-Path $RepoRoot)) { throw "Missing $RepoRoot" }
Set-Location $RepoRoot
$logDir = Join-Path $RepoRoot "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }
$log = Join-Path $logDir "pipeline-watchdog.log"

function Write-Log([string]$msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | $msg"
    Add-Content -Path $log -Value $line -ErrorAction SilentlyContinue
    Write-Host $line
}

function Import-DotEnv {
    $envFile = Join-Path $RepoRoot ".env"
    if (-not (Test-Path $envFile)) { return }
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
        $pair = $_.Split("=", 2)
        if ($pair.Count -eq 2) {
            [Environment]::SetEnvironmentVariable($pair[0].Trim(), $pair[1].Trim(), "Process")
        }
    }
    if (-not $env:QAT_EXECUTION_MODE) { $env:QAT_EXECUTION_MODE = "paper" }
    if (-not $env:QAT_TRADING_SIMULATION_MODE) { $env:QAT_TRADING_SIMULATION_MODE = "true" }
    if (-not $env:QAT_TIGER_PAPER_TRADING) { $env:QAT_TIGER_PAPER_TRADING = "true" }
    if (-not $env:QAT_US_24H_TRADING) { $env:QAT_US_24H_TRADING = "true" }
    if (-not $env:QAT_TRADING_HOURS_ONLY) { $env:QAT_TRADING_HOURS_ONLY = "false" }
    if (-not $env:QAT_TIGER_ACCOUNT) { $env:QAT_TIGER_ACCOUNT = "21837535188693626" }
    if (-not $env:QAT_EXEC_TIGER_ACCOUNT) { $env:QAT_EXEC_TIGER_ACCOUNT = "21837535188693626" }
    $env:PYTHONPATH = $RepoRoot
    $env:QAT_PROJECT_ROOT = $RepoRoot
}

function Test-PipelineAlive {
    $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "trading_pipeline|run_pipeline" }
    return [bool]$procs
}

function Start-Detached([string]$CommandLine) {
    try {
        $r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
            CommandLine = $CommandLine
            CurrentDirectory = $RepoRoot
        }
        if ($r.ReturnValue -eq 0) {
            Write-Log ("detached pid={0}" -f $r.ProcessId)
            return $true
        }
        Write-Log ("Win32_Process.Create failed rc={0}" -f $r.ReturnValue)
    } catch {
        Write-Log ("Win32_Process.Create error: {0}" -f $_.Exception.Message)
    }
    try {
        Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", $CommandLine) -WorkingDirectory $RepoRoot -WindowStyle Hidden | Out-Null
        return $true
    } catch {
        Write-Log ("Start-Process fallback failed: {0}" -f $_.Exception.Message)
        return $false
    }
}

function Start-Pipeline {
    Write-Log "Starting trading pipeline (paper / Tiger sim)..."
    Import-DotEnv
    $py = "python"
    if (Test-Path "C:\Program Files\Python312\python.exe") {
        $py = "C:\Program Files\Python312\python.exe"
    }
    $runner = Join-Path $RepoRoot "scripts\run_pipeline.py"
    if (-not (Test-Path $runner)) {
        $runner = Join-Path $RepoRoot "trading_pipeline.py"
    }
    $batDir = Join-Path $RepoRoot "cache\windows_pids"
    New-Item -ItemType Directory -Force -Path $batDir | Out-Null
    $bat = Join-Path $batDir "start_pipeline.bat"
    $outLog = Join-Path $logDir "pipeline-stdout.log"
    $errLog = Join-Path $logDir "pipeline-stderr.log"

    $runLine = '"{0}" -u "{1}" >> "{2}" 2>> "{3}"' -f $py, $runner, $outLog, $errLog
    $envLines = @(
        "@echo off",
        ("set PYTHONPATH={0}" -f $RepoRoot),
        ("set QAT_PROJECT_ROOT={0}" -f $RepoRoot),
        ("set QAT_EXECUTION_MODE={0}" -f $env:QAT_EXECUTION_MODE),
        ("set QAT_TRADING_SIMULATION_MODE={0}" -f $env:QAT_TRADING_SIMULATION_MODE),
        ("set QAT_TIGER_PAPER_TRADING={0}" -f $env:QAT_TIGER_PAPER_TRADING),
        ("set QAT_US_24H_TRADING={0}" -f $env:QAT_US_24H_TRADING),
        ("set QAT_TRADING_HOURS_ONLY={0}" -f $env:QAT_TRADING_HOURS_ONLY),
        ("set QAT_TIGER_ID={0}" -f $env:QAT_TIGER_ID),
        ("set QAT_TIGER_ACCOUNT={0}" -f $env:QAT_TIGER_ACCOUNT),
        ("set QAT_EXEC_TIGER_ACCOUNT={0}" -f $env:QAT_EXEC_TIGER_ACCOUNT),
        ("set QAT_TIGER_PRIVATE_KEY_PATH={0}" -f $env:QAT_TIGER_PRIVATE_KEY_PATH),
        ("set QAT_TIGER_LICENSE={0}" -f $env:QAT_TIGER_LICENSE),
        ("set QAT_ENABLED_MARKETS={0}" -f $env:QAT_ENABLED_MARKETS),
        ("set QAT_MARKET_ROTATION={0}" -f $env:QAT_MARKET_ROTATION),
        ("cd /d {0}" -f $RepoRoot),
        $runLine
    )
    Set-Content -Path $bat -Value ($envLines -join "`r`n") -Encoding ASCII

    $cmd = 'cmd.exe /c "{0}"' -f $bat
    $ok = Start-Detached $cmd
    Start-Sleep -Seconds 4
    return $ok
}

function Invoke-Check {
    if (Test-PipelineAlive) {
        Write-Log "pipeline OK"
        return $true
    }
    Write-Log "pipeline DOWN - restarting"
    Start-Pipeline | Out-Null
    if (Test-PipelineAlive) {
        Write-Log "pipeline restarted OK"
        return $true
    }
    Write-Log "pipeline restart FAILED"
    return $false
}

if ($InstallTask) {
    $wrapper = Join-Path $RepoRoot "scripts\_run_pipeline_watchdog_logged.ps1"
    $watchdogPs1 = Join-Path $RepoRoot "scripts\windows_pipeline_watchdog.ps1"
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
    Register-ScheduledTask -TaskName "QAT-Pipeline-Watchdog" -Action $action `
        -Trigger @($trigger, $onceTrig) -Principal $prin -Settings $settings `
        -Description "QAT: keep trading_pipeline process alive (Tiger paper)" -Force | Out-Null
    Write-Log "Registered QAT-Pipeline-Watchdog"
    $alive = Invoke-Check
    if (-not $alive) { exit 1 }
    exit 0
}

if ($Once) {
    $alive = Invoke-Check
    if (-not $alive) { exit 1 }
    exit 0
}

Write-Log ("Watchdog loop every {0} s" -f $IntervalSeconds)
while ($true) {
    Invoke-Check | Out-Null
    Start-Sleep -Seconds $IntervalSeconds
}
