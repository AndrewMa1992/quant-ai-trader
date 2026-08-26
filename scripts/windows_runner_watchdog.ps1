# Keep the GitHub Actions self-hosted runner alive on Lightsail Windows.
# Without it a merge to main sits in "queued" forever and CD never deploys.
# ASCII-only (PS 5.1). Never restarts the runner while a job is executing.
#   .\scripts\windows_runner_watchdog.ps1 -InstallTask
#   .\scripts\windows_runner_watchdog.ps1 -Once

param(
    [string]$RepoRoot = "C:\quant-ai-trader",
    [string]$RunnerDir = "C:\actions-runner",
    [int]$IntervalSeconds = 300,
    [switch]$InstallTask,
    [switch]$Once
)

$ErrorActionPreference = "Continue"
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
             [System.Environment]::GetEnvironmentVariable("Path", "User")

$logDir = Join-Path $RepoRoot "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }
$log = Join-Path $logDir "runner-watchdog.log"

function Write-Log([string]$msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | $msg"
    Add-Content -Path $log -Value $line -ErrorAction SilentlyContinue
    Write-Host $line
}

function Get-RunnerService {
    return (Get-Service -Name "actions.runner.*" -ErrorAction SilentlyContinue | Select-Object -First 1)
}

function Test-RunnerListener {
    $p = Get-Process -Name "Runner.Listener" -ErrorAction SilentlyContinue
    return [bool]$p
}

function Test-RunnerAlive {
    $svc = Get-RunnerService
    if ($svc -and $svc.Status -eq "Running") { return $true }
    return (Test-RunnerListener)
}

function Start-RunnerService {
    $svc = Get-RunnerService
    if (-not $svc) { return $false }
    Write-Log ("starting service {0} (was {1})" -f $svc.Name, $svc.Status)
    try {
        Start-Service -Name $svc.Name -ErrorAction Stop
        Start-Sleep -Seconds 5
        return ((Get-Service -Name $svc.Name).Status -eq "Running")
    } catch {
        Write-Log ("Start-Service failed: {0}" -f $_.Exception.Message)
    }
    $svcCmd = Join-Path $RunnerDir "svc.cmd"
    if (Test-Path $svcCmd) {
        try {
            Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", ('"{0}" start' -f $svcCmd)) `
                -WorkingDirectory $RunnerDir -Wait -WindowStyle Hidden | Out-Null
            Start-Sleep -Seconds 5
            return (Test-RunnerAlive)
        } catch {
            Write-Log ("svc.cmd start failed: {0}" -f $_.Exception.Message)
        }
    }
    return $false
}

function Start-RunnerInteractive {
    # No Windows service configured: fall back to run.cmd, detached and hidden.
    $runCmd = Join-Path $RunnerDir "run.cmd"
    if (-not (Test-Path $runCmd)) {
        Write-Log ("missing {0} - runner not installed, see scripts\windows_install_runner.ps1" -f $runCmd)
        return $false
    }
    $hidden = Join-Path $RepoRoot "scripts\windows_hidden_start.ps1"
    if (Test-Path $hidden) {
        . $hidden
        $pidVal = Start-QatHiddenBat -BatPath $runCmd -WorkingDirectory $RunnerDir -CommandMatch "Runner.Listener"
        if ($pidVal) {
            Write-Log ("run.cmd hidden pid={0}" -f $pidVal)
            Start-Sleep -Seconds 8
            return (Test-RunnerAlive)
        }
    }
    try {
        Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", $runCmd) `
            -WorkingDirectory $RunnerDir -WindowStyle Hidden | Out-Null
        Start-Sleep -Seconds 8
        return (Test-RunnerAlive)
    } catch {
        Write-Log ("run.cmd start failed: {0}" -f $_.Exception.Message)
        return $false
    }
}

function Invoke-Check {
    if (Test-RunnerAlive) {
        Write-Log "runner OK"
        return $true
    }
    Write-Log "runner DOWN - restarting"
    if (Start-RunnerService) {
        Write-Log "runner service restarted OK"
        return $true
    }
    if (Start-RunnerInteractive) {
        Write-Log "runner run.cmd restarted OK"
        return $true
    }
    Write-Log "runner restart FAILED - CD jobs will stay queued"
    return $false
}

if ($InstallTask) {
    $wrapper = Join-Path $RepoRoot "scripts\_run_runner_watchdog_logged.ps1"
    $watchdogPs1 = Join-Path $RepoRoot "scripts\windows_runner_watchdog.ps1"
    $wrapperLines = @(
        '$ErrorActionPreference=''Continue''',
        ('Set-Location ''{0}''' -f $RepoRoot),
        ('powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{0}" -Once -RunnerDir "{1}"' -f $watchdogPs1, $RunnerDir)
    )
    Set-Content -Path $wrapper -Value ($wrapperLines -join "`r`n") -Encoding ASCII

    $arg = '-NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $wrapper
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory $RepoRoot
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $onceTrig = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
        -RepetitionInterval (New-TimeSpan -Minutes 5) `
        -RepetitionDuration ([TimeSpan]::FromDays(3650))
    $prin = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest -LogonType ServiceAccount
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 0)
    Register-ScheduledTask -TaskName "QAT-Runner-Watchdog" -Action $action `
        -Trigger @($trigger, $onceTrig) -Principal $prin -Settings $settings `
        -Description "QAT: keep the GitHub Actions self-hosted runner online" -Force | Out-Null
    Write-Log "Registered QAT-Runner-Watchdog"
    exit 0
}

if ($Once) {
    $alive = Invoke-Check
    if (-not $alive) { exit 1 }
    exit 0
}

Write-Log ("Runner watchdog loop every {0} s" -f $IntervalSeconds)
while ($true) {
    Invoke-Check | Out-Null
    Start-Sleep -Seconds $IntervalSeconds
}
