# ═══════════════════════════════════════════════════════════════
# Quant AI Trader — Windows 守护进程安装
# 功能：注册为 Windows 任务计划程序（开机自启 + 被杀后自恢复）
#
# 以管理员身份运行此脚本
# ═══════════════════════════════════════════════════════════════
$ErrorActionPreference = "Stop"
$host.UI.RawUI.WindowTitle = "QuantAI - Daemon Installer"

$TaskName     = "QuantAITrader"
$ProjectRoot  = "D:\workbuddyspace\Claw\quant-ai-trader"
$DaemonScript = "$ProjectRoot\daemon_win.ps1"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Quant AI Trader - 守护进程安装" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# ═══════════════════════════════════════════════════════════════
# Step 1: 停止旧任务
# ═══════════════════════════════════════════════════════════════
Write-Host "[1/4] Stopping existing task..." -ForegroundColor Yellow
try {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "  Old task cleaned up" -ForegroundColor Gray
} catch {
    Write-Host "  No existing task (clean)" -ForegroundColor Gray
}

# ═══════════════════════════════════════════════════════════════
# Step 2: 停止当前运行的服务实例
# ═══════════════════════════════════════════════════════════════
Write-Host "[2/4] Stopping current instances..." -ForegroundColor Yellow

$ports = @(8001, 5180)
foreach ($port in $ports) {
    $conns = netstat -ano 2>$null | Select-String ":$port\s+.*LISTENING"
    foreach ($conn in $conns) {
        $pidStr = ($conn -split '\s+')[-1]
        if ($pidStr -match '^\d+$') {
            try {
                Stop-Process -Id ([int]$pidStr) -Force -ErrorAction SilentlyContinue
                Write-Host "  Killed process on :$port (PID $pidStr)" -ForegroundColor Gray
            } catch {}
        }
    }
}

Get-Process -Name "python" -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.CommandLine -match "auto_trader|run_backend" 2>$null) {
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        Write-Host "  Killed python PID $($_.Id)" -ForegroundColor Gray
    }
}
Start-Sleep -Seconds 2
Write-Host "  Cleanup done" -ForegroundColor Green

# ═══════════════════════════════════════════════════════════════
# Step 3: 创建任务计划
# ═══════════════════════════════════════════════════════════════
Write-Host "[3/4] Registering scheduled task..." -ForegroundColor Yellow

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$DaemonScript`""

# ★ 核心：登录时触发一次
$Trigger = New-ScheduledTaskTrigger -AtLogOn

# ★ 守护：每 1 分钟检查一次，如果任务没在运行就重启
#    这样即使任务被杀也会在 1 分钟内恢复
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -Compatibility Win8 `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Days 365) `
    -DisallowDemandStart:$false

$Principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Highest

try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Principal $Principal `
        -Settings $settings `
        -Description "Quant AI Trader - 量化AI交易系统守护进程 (自动重启)" `
        -Force 2>$null

    Write-Host "  Scheduled task registered" -ForegroundColor Green
} catch {
    Write-Host "  ERROR: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Please run this script as Administrator." -ForegroundColor Yellow
    exit 1
}

# ═══════════════════════════════════════════════════════════════
# Step 4: 立即启动任务
# ═══════════════════════════════════════════════════════════════
Write-Host "[4/4] Starting daemon now..." -ForegroundColor Yellow

try {
    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 5
    Write-Host "  Daemon launched" -ForegroundColor Green
} catch {
    Write-Host "  WARNING: Could not auto-start (will start at next login): $_" -ForegroundColor Yellow
}

# ═══════════════════════════════════════════════════════════════
# 验证
# ═══════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  服务状态报告" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

Start-Sleep -Seconds 20

# 检查各服务
try {
    $r = Invoke-WebRequest -Uri "http://localhost:8001/health" -TimeoutSec 5 -UseBasicParsing
    Write-Host "  Backend  :8001  RUNNING" -ForegroundColor Green
} catch {
    Write-Host "  Backend  :8001  STARTING (wait...)" -ForegroundColor Yellow
}

try {
    $r = Invoke-WebRequest -Uri "http://localhost:5180" -TimeoutSec 5 -UseBasicParsing
    Write-Host "  Frontend :5180  RUNNING" -ForegroundColor Green
} catch {
    Write-Host "  Frontend :5180  STARTING (wait...)" -ForegroundColor Yellow
}

$tr = Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -match "auto_trader" 2>$null
}
if ($tr) {
    Write-Host "  AutoTrader      RUNNING" -ForegroundColor Green
} else {
    Write-Host "  AutoTrader      STARTING (wait...)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Web UI:   http://localhost:5180" -ForegroundColor White
Write-Host "  Backend:  http://localhost:8001" -ForegroundColor White
Write-Host "  API Docs: http://localhost:8001/docs" -ForegroundColor White
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "常用管理命令:" -ForegroundColor Yellow
Write-Host "  Get-ScheduledTask -TaskName QuantAITrader | Select State" -ForegroundColor Gray
Write-Host "  Stop-ScheduledTask  -TaskName QuantAITrader" -ForegroundColor Gray
Write-Host "  Start-ScheduledTask -TaskName QuantAITrader" -ForegroundColor Gray
Write-Host "  schtasks /Change /TN QuantAITrader /DISABLE" -ForegroundColor Gray
Write-Host "  schtasks /Change /TN QuantAITrader /ENABLE" -ForegroundColor Gray
Write-Host "  tail -f D:\workbuddyspace\Claw\quant-ai-trader\logs\daemon.log" -ForegroundColor Gray
Write-Host ""
Write-Host " 守护进程安装完成！" -ForegroundColor Green
Write-Host "  - 开机自启:  登录时自动启动" -ForegroundColor Green
Write-Host "  - 被杀自恢复: 进程被杀后 1 分钟内自动重启" -ForegroundColor Green
Write-Host "  - 代码变更:  自动检测 .py 文件变动并重启服务" -ForegroundColor Green
Write-Host "  - Git自动拉取: 每10分钟拉取最新代码" -ForegroundColor Green
Write-Host ""
