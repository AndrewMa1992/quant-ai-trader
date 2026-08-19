# Keep trading_pipeline.py alive on Lightsail Windows.
# DeployScriptVersion: 1
# Run once (Admin) or register as scheduled task:
#   .\scripts\windows_pipeline_watchdog.ps1 -InstallTask
#   .\scripts\windows_pipeline_watchdog.ps1 -Once   # single health check + restart if down

param(
    [string]$RepoRoot = "C:\quant-ai-trader",
    [string]$Branch = "cursor/quant-upgrade-a75f",
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

function Test-PipelineAlive {
    $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "trading_pipeline|run_pipeline" }
    return [bool]$procs
}

function Start-Pipeline {
    Write-Log "Starting trading pipeline..."
    $py = "python"
    if (Test-Path "C:\Program Files\Python312\python.exe") {
        $py = "C:\Program Files\Python312\python.exe"
    }
    $runner = Join-Path $RepoRoot "scripts\run_pipeline.py"
    if (-not (Test-Path $runner)) {
        $runner = Join-Path $RepoRoot "trading_pipeline.py"
    }
    Start-Process -FilePath $py -ArgumentList @("-u", $runner) `
        -WorkingDirectory $RepoRoot -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDir "pipeline-stdout.log") `
        -RedirectStandardError (Join-Path $logDir "pipeline-stderr.log")
}

if ($InstallTask) {
    $wrapper = Join-Path $RepoRoot "scripts\_run_pipeline_watchdog_logged.ps1"
    $body = @"
`$ErrorActionPreference='Continue'
Set-Location '$RepoRoot'
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path '$RepoRoot' 'scripts\windows_pipeline_watchdog.ps1')
"@
    Set-Content -Path $wrapper -Value $body -Encoding UTF8
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$wrapper`"" `
        -WorkingDirectory $RepoRoot
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $once = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
        -RepetitionInterval (New-TimeSpan -Minutes 2) `
        -RepetitionDuration ([TimeSpan]::FromDays(3650))
    $prin = New-ScheduledTaskPrincipal -UserId "Administrator" -RunLevel Highest -LogonType Interactive
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 0)
    Register-ScheduledTask -TaskName "QAT-Pipeline-Watchdog" -Action $action `
        -Trigger @($trigger, $once) -Principal $prin -Settings $settings `
        -Description "QAT: keep trading_pipeline process alive" -Force | Out-Null
    Write-Log "Registered QAT-Pipeline-Watchdog"
    exit 0
}

function Invoke-Check {
    if (Test-PipelineAlive) {
        Write-Log "pipeline OK"
    } else {
        Write-Log "pipeline DOWN — restarting"
        Start-Pipeline
    }
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
