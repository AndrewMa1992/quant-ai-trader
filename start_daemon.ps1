# start_daemon.ps1 - called by Scheduled Task QuantAI-V2-Daemon
# Silently start daemon_forever.bat
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$batPath = Join-Path $projectRoot "daemon_forever.bat"
if (Test-Path $batPath) {
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c `"$batPath`"" -WindowStyle Hidden -WorkingDirectory $projectRoot
}
