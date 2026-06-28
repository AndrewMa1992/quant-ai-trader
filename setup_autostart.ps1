# Quant AI Trader v2 — 开机自启动安装脚本
# 以管理员身份运行: powershell -ExecutionPolicy Bypass -File setup_autostart.ps1

$taskName = "QuantAI-Trader-v2"
$batPath = "E:\workbuddyspace\Claw\quant-ai-trader\daemon_forever.bat"
$workDir = "E:\workbuddyspace\Claw\quant-ai-trader"

# 先删除旧任务
schtasks /delete /tn $taskName /f 2>$null

# 创建计划任务: 登录后运行, 最高权限, 不限时
schtasks /create `
  /tn $taskName `
  /tr "cmd.exe /c 'cd /d $workDir && start /MIN $batPath'" `
  /sc ONLOGON `
  /rl HIGHEST `
  /delay 0000:30 `
  /f

Write-Host "✅ 开机自启动已设置: $taskName"
Write-Host "   路径: $batPath"
Write-Host "   延迟: 登录后30秒启动 (等网络就绪)"
