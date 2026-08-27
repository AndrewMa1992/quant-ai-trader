# Quant AI Trader v2 — boot autostart installer
# Run as administrator: powershell -ExecutionPolicy Bypass -File setup_autostart.ps1

$taskName = "QuantAI-Trader-v2"
$batPath = "E:\workbuddyspace\Claw\quant-ai-trader\daemon_forever.bat"
$workDir = "E:\workbuddyspace\Claw\quant-ai-trader"

# Remove the old task first
schtasks /delete /tn $taskName /f 2>$null

# Create scheduled task: run at logon, highest privileges, no time limit
schtasks /create `
  /tn $taskName `
  /tr "cmd.exe /c 'cd /d $workDir && start /MIN $batPath'" `
  /sc ONLOGON `
  /rl HIGHEST `
  /delay 0000:30 `
  /f

Write-Host "✅ Boot autostart configured: $taskName"
Write-Host "   Path: $batPath"
Write-Host "   Delay: start 30 seconds after logon (wait for network)"
