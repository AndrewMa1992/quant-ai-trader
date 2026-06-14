# Quant AI Trader - Windows boot installer
$TaskName = "QuantAI-Trader-Daemon"
$ScriptPath = "$PSScriptRoot\daemon_win.ps1"
$WorkingDir = $PSScriptRoot

$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")
if (-not $isAdmin) {
    Write-Host "ERROR: Run as Administrator!"
    Read-Host
    exit 1
}

# Remove old task
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

# Create action
$arg = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $ScriptPath + '"'
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory $WorkingDir

# Trigger: at startup
$trigger = New-ScheduledTaskTrigger -AtStartup

# Settings: auto-restart on crash
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -DontStopOnIdleEnd `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

# SYSTEM account
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

# Register
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force

# Start immediately
Start-ScheduledTask -TaskName $TaskName

Write-Host "Installed: $TaskName"
Write-Host "Logs: $WorkingDir\logs\daemon.log"
Write-Host "Manage: taskschd.msc"
Write-Host "Uninstall: Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false"
