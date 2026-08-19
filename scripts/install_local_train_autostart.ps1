# One-time: schedule automatic local GPU train + Git sync to Lightsail.
# Run as Administrator ON THE RTX 3060 PC (not on Lightsail):
#   .\scripts\install_local_train_autostart.ps1
#   .\scripts\install_local_train_autostart.ps1 -DailyAt "02:30" -Epochs 40
#
# Creates:
#   QAT-Local-TrainSync  - daily train_and_sync.ps1

param(
    [string]$RepoRoot = "",
    [string]$Branch = "cursor/quant-upgrade-a75f",
    [string]$DailyAt = "02:30",
    [int]$Epochs = 40,
    [string]$Tickers = "AAPL,MSFT,GOOGL,AMZN,NVDA,META,TSLA,SPY,QQQ,IWM",
    [switch]$SkipRl,
    [switch]$RunNow
)

$ErrorActionPreference = "Stop"

if (-not $RepoRoot) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
$RepoRoot = (Resolve-Path $RepoRoot).Path
$script = Join-Path $RepoRoot "scripts\train_and_sync.ps1"
if (-not (Test-Path $script)) { throw "Missing $script - git pull first" }

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run as Administrator on the GPU PC."
}

$argParts = @(
    "-NoProfile",
    "-ExecutionPolicy Bypass",
    "-File `"$script`"",
    "-Branch $Branch",
    "-Epochs $Epochs",
    "-Tickers `"$Tickers`""
)
if ($SkipRl) { $argParts += "-SkipRl" }
$argLine = $argParts -join " "

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argLine -WorkingDirectory $RepoRoot
# Daily at HH:mm
$parts = $DailyAt.Split(":")
$hour = [int]$parts[0]
$minute = [int]$parts[1]
$trigger = New-ScheduledTaskTrigger -Daily -At (Get-Date -Hour $hour -Minute $minute -Second 0)
$prin = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest -LogonType Interactive
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 6)

Register-ScheduledTask -TaskName "QAT-Local-TrainSync" -Action $action -Trigger $trigger `
    -Principal $prin -Settings $settings `
    -Description "Quant AI Trader: daily GPU train + push models for Lightsail AutoCD" -Force | Out-Null

Write-Host "[ok] Scheduled task: QAT-Local-TrainSync"
Write-Host "     Daily at $DailyAt | Branch=$Branch | Epochs=$Epochs"
Write-Host "     Lightsail AutoCD will pull within ~10 min after each push"
Write-Host "View: taskschd.msc"

if ($RunNow) {
    Write-Host "[..] RunNow train_and_sync..."
    $rn = @("-Branch", $Branch, "-Epochs", "$Epochs", "-Tickers", $Tickers)
    if ($SkipRl) { $rn += "-SkipRl" }
    & powershell -NoProfile -ExecutionPolicy Bypass -File $script @rn
}
