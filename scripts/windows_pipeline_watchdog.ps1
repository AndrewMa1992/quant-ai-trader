# Keep trading_pipeline.py alive on Lightsail Windows (paper / Tiger sim).
# DeployScriptVersion: 2
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
    Add-Content -Path $log -Value $line
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
    $bat = Join-Path $RepoRoot "cache\windows_pids\start_pipeline.bat"
    New-Item -ItemType Directory -Force -Path (Split-Path $bat) | Out-Null
    $envLines = @(
        "@echo off",
        "set PYTHONPATH=$RepoRoot",
        "set QAT_PROJECT_ROOT=$RepoRoot",
        "set QAT_EXECUTION_MODE=$($env:QAT_EXECUTION_MODE)",
        "set QAT_TRADING_SIMULATION_MODE=$($env:QAT_TRADING_SIMULATION_MODE)",
        "set QAT_TIGER_PAPER_TRADING=$($env:QAT_TIGER_PAPER_TRADING)",
        "set QAT_US_24H_TRADING=$($env:QAT_US_24H_TRADING)",
        "set QAT_TRADING_HOURS_ONLY=$($env:QAT_TRADING_HOURS_ONLY)",
        "set QAT_TIGER_ID=$($env:QAT_TIGER_ID)",
        "set QAT_TIGER_ACCOUNT=$($env:QAT_TIGER_ACCOUNT)",
        "set QAT_EXEC_TIGER_ACCOUNT=$($env:QAT_EXEC_TIGER_ACCOUNT)",
        "set QAT_TIGER_PRIVATE_KEY_PATH=$($env:QAT_TIGER_PRIVATE_KEY_PATH)",
        "set QAT_TIGER_LICENSE=$($env:QAT_TIGER_LICENSE)",
        "set QAT_ENABLED_MARKETS=$($env:QAT_ENABLED_MARKETS)",
        "set QAT_MARKET_ROTATION=$($env:QAT_MARKET_ROTATION)",
        "cd /d `"$RepoRoot`"",
        "`"$py`" -u `"$runner`""
    )
    Set-Content -Path $bat -Value ($envLines -join "`r`n") -Encoding ASCII
    Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", "`"$bat`"") `
        -WorkingDirectory $RepoRoot -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDir "pipeline-stdout.log") `
        -RedirectStandardError (Join-Path $logDir "pipeline-stderr.log")
    Start-Sleep -Seconds 3
}

function Invoke-Check {
    if (Test-PipelineAlive) {
        Write-Log "pipeline OK"
    } else {
        Write-Log "pipeline DOWN — restarting"
        Start-Pipeline
        if (Test-PipelineAlive) { Write-Log "pipeline restarted OK" } else { Write-Log "pipeline restart FAILED" }
    }
}

if ($InstallTask) {
    $wrapper = Join-Path $RepoRoot "scripts\_run_pipeline_watchdog_logged.ps1"
    $body = @"
`$ErrorActionPreference='Continue'
Set-Location '$RepoRoot'
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path '$RepoRoot' 'scripts\windows_pipeline_watchdog.ps1') -Once
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
    Register-ScheduledTask -TaskName "QAT-Pipeline-Watchdog" -Action $action `
        -Trigger @($trigger, $onceTrig) -Principal $prin -Settings $settings `
        -Description "QAT: keep trading_pipeline process alive (Tiger paper)" -Force | Out-Null
    Write-Log "Registered QAT-Pipeline-Watchdog"
    Invoke-Check
    exit 0
}

if ($Once) {
    Invoke-Check
    exit 0
}

Write-Log "Watchdog loop every $IntervalSeconds s"
while ($true) {
    Invoke-Check
    Start-Sleep -Seconds $IntervalSeconds
}
