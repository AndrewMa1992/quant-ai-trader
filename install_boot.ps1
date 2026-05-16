# Quant AI Trader - 开机自启动安装 (PowerShell)
# 以管理员身份运行

$taskName = "QuantAITrader"
$scriptPath = "G:\workbuddyspace\quant-ai-trader\boot_start.bat"

# 方法1: 用 Windows 任务计划程序 (最可靠)
try {
    $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$scriptPath`""
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -Compatibility Win8

    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force 2>$null
    
    if ($?) {
        Write-Host "✅ [任务计划] 开机自启动已设置 - $taskName" -ForegroundColor Green
        Write-Host "   触发: 用户登录时自动启动"
    }
} catch {
    Write-Host "⚠️ [任务计划] 设置失败（可能需要管理员权限）: $_" -ForegroundColor Yellow
    Write-Host "   使用开机启动文件夹方案..."
    
    # 方法2: 启动文件夹 (不需要管理员)
    $startupDir = [Environment]::GetFolderPath("Startup")
    $lnkPath = Join-Path $startupDir "QuantAITrader.bat"
    "@echo off`nstart /MIN python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --app-dir `"G:\workbuddyspace\quant-ai-trader`"`ncd /d G:\workbuddyspace\quant-ai-trader\frontend`nstart /MIN npm run dev" | Set-Content $lnkPath -Encoding ASCII
    Write-Host "✅ [启动文件夹] 开机启动已设置" -ForegroundColor Green
    Write-Host "   路径: $lnkPath"
}

Write-Host ""
Write-Host "===================================="
Write-Host "  Quant AI Trader - 开机启动" -ForegroundColor Cyan
Write-Host "===================================="
Write-Host ""

# 测试当前状态
Write-Host "当前服务状态:" -ForegroundColor Yellow
$b = netstat -ano 2>&1 | Select-String "LISTENING" | Select-String ":8000"
if ($b) { Write-Host "  Backend :8000 ✅ 已运行" -ForegroundColor Green } else { Write-Host "  Backend :8000 ❌ 未运行" -ForegroundColor Red }

$f = netstat -ano 2>&1 | Select-String "LISTENING" | Select-String ":5173"
if ($f) { Write-Host "  Frontend:5173 ✅ 已运行" -ForegroundColor Green } else { Write-Host "  Frontend:5173 ❌ 未运行" -ForegroundColor Red }

Write-Host ""
Write-Host "打开浏览器访问: http://localhost:5173" -ForegroundColor Cyan
Write-Host "===================================="
