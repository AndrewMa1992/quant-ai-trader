# One-shot: enable auto-run + auto-deploy on Lightsail Windows
# DeployScriptVersion: 5
# Run as Administrator:
#   .\scripts\windows_install_autostart.ps1
#   .\scripts\windows_install_autostart.ps1 -Branch cursor/quant-upgrade-a75f
#   .\scripts\windows_install_autostart.ps1 -Branch main -IntervalMinutes 10
#
# Creates Scheduled Tasks:
#   QAT-Paper-Boot     - at startup: pull + deploy (Smart)
#   QAT-Paper-AutoCD   - every N minutes: Smart pull + deploy if changed/unhealthy
#   QAT-Actions-Runner - at logon: start run.cmd if C:\actions-runner exists (optional CD via Actions)

[CmdletBinding()]
param(
    [string]$Branch = "cursor/quant-upgrade-a75f",
    [string]$RepoRoot = "C:\quant-ai-trader",
    [int]$IntervalMinutes = 10,
    [string]$RunnerDir = "C:\actions-runner",
    [switch]$SkipRunnerTask,
    [switch]$RunNow
)

$ErrorActionPreference = "Stop"

$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
             [System.Environment]::GetEnvironmentVariable("Path", "User")

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script as Administrator."
}

if (-not (Test-Path $RepoRoot)) {
    throw "Repo not found: $RepoRoot"
}

$cdScript = Join-Path $RepoRoot "scripts\windows_cd_deploy.ps1"
if (-not (Test-Path $cdScript)) {
    throw "Missing $cdScript - git pull latest first"
}

function Register-QatTask {
    param(
        [string]$Name,
        [string]$Args,
        [object]$Trigger,
        [string]$Description
    )
    $action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$cdScript`" $Args" `
        -WorkingDirectory $RepoRoot
    $prin = New-ScheduledTaskPrincipal -UserId "Administrator" -RunLevel Highest -LogonType Interactive
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $Trigger `
        -Principal $prin -Settings $settings -Description $Description -Force | Out-Null
    Write-Host "[ok] Scheduled task: $Name"
}

Write-Host "============================================"
Write-Host "  QAT Autostart + Auto CD"
Write-Host "  Root:   $RepoRoot"
Write-Host "  Branch: $Branch"
Write-Host "  Every:  $IntervalMinutes min"
Write-Host "============================================"

# Boot: ensure stack is up after reboot
$bootTrigger = New-ScheduledTaskTrigger -AtStartup
Register-QatTask -Name "QAT-Paper-Boot" `
    -Args "-Branch $Branch -Smart" `
    -Trigger $bootTrigger `
    -Description "Quant AI Trader paper stack: pull branch and start on boot"

# Periodic Smart CD (no GitHub runner required)
$once = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration ([TimeSpan]::FromDays(3650))
Register-QatTask -Name "QAT-Paper-AutoCD" `
    -Args "-Branch $Branch -Smart" `
    -Trigger $once `
    -Description "Quant AI Trader: every $IntervalMinutes min pull origin/$Branch and redeploy if needed"

# Optional: keep Actions runner online via run.cmd
if (-not $SkipRunnerTask) {
    $runCmd = Join-Path $RunnerDir "run.cmd"
    if (Test-Path $runCmd) {
        $runnerAction = New-ScheduledTaskAction `
            -Execute "cmd.exe" `
            -Argument "/c `"$runCmd`"" `
            -WorkingDirectory $RunnerDir
        $logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User "Administrator"
        $prin = New-ScheduledTaskPrincipal -UserId "Administrator" -RunLevel Highest -LogonType Interactive
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
        Register-ScheduledTask -TaskName "QAT-Actions-Runner" -Action $runnerAction -Trigger $logonTrigger `
            -Principal $prin -Settings $settings `
            -Description "GitHub Actions self-hosted runner (run.cmd)" -Force | Out-Null
        Write-Host "[ok] Scheduled task: QAT-Actions-Runner (AtLogOn run.cmd)"
    } else {
        Write-Host "[warn] No $runCmd - skip QAT-Actions-Runner (optional)"
    }
}

Write-Host ""
Write-Host "Tasks registered. View: taskschd.msc"
Write-Host "  QAT-Paper-Boot"
Write-Host "  QAT-Paper-AutoCD"
if (-not $SkipRunnerTask) { Write-Host "  QAT-Actions-Runner (if runner present)" }
Write-Host ""
Write-Host "Flow:"
Write-Host "  1) Push/merge to branch: $Branch"
Write-Host "  2) Within ~$IntervalMinutes min server pulls and redeploys"
Write-Host "  3) Reboot also auto-starts paper mode"
Write-Host "Logs: $RepoRoot\logs\cd-deploy.log"

if ($RunNow) {
    Write-Host "[..] RunNow: deploying once..."
    & powershell -ExecutionPolicy Bypass -File $cdScript -Branch $Branch -Force
    if ($LASTEXITCODE -ne 0) { throw "RunNow deploy failed" }
    Write-Host "[ok] RunNow finished"
}
