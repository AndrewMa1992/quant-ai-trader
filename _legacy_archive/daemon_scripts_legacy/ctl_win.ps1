# ═══════════════════════════════════════════════════════════════
# Quant AI Trader — Windows 服务控制脚本
# 用法: .\ctl_win.ps1 {start|stop|restart|status|logs}
# ═══════════════════════════════════════════════════════════════
param(
    [ValidateSet("start", "stop", "restart", "status", "logs")]
    [string]$Action = "status"
)

$TaskName = "QuantAITrader"
$ProjectRoot = "D:\workbuddyspace\Claw\quant-ai-trader"
$LogDir = "$ProjectRoot\logs"

function Show-Status {
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "  Quant AI Trader — 服务状态" -ForegroundColor Cyan
    Write-Host "============================================" -ForegroundColor Cyan

    # 任务计划状态
    try {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
        Write-Host "  Scheduled Task: $($task.State)" -ForegroundColor $(if ($task.State -eq "Running") { "Green" } else { "Yellow" })
    } catch {
        Write-Host "  Scheduled Task: NOT REGISTERED" -ForegroundColor Red
    }

    Write-Host ""

    # Backend
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:8001/health" -TimeoutSec 3 -UseBasicParsing
        Write-Host "  Backend  :8001  RUNNING" -ForegroundColor Green
    } catch {
        Write-Host "  Backend  :8001  DOWN" -ForegroundColor Red
    }

    # Frontend
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:5180" -TimeoutSec 3 -UseBasicParsing
        Write-Host "  Frontend :5180  RUNNING" -ForegroundColor Green
    } catch {
        Write-Host "  Frontend :5180  DOWN" -ForegroundColor Red
    }

    # Auto Trader
    $tr = Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -match "auto_trader" 2>$null
    }
    if ($tr) {
        Write-Host "  AutoTrader      RUNNING (PID $($tr[0].Id))" -ForegroundColor Green
    } else {
        Write-Host "  AutoTrader      DOWN" -ForegroundColor Red
    }

    Write-Host ""
    Write-Host "  Web UI:   http://localhost:5180" -ForegroundColor White
    Write-Host "  Backend:  http://localhost:8001" -ForegroundColor White
    Write-Host "  API Docs: http://localhost:8001/docs" -ForegroundColor White
    Write-Host "  Daemon Log: $LogDir\daemon.log" -ForegroundColor Gray
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host ""
}

switch ($Action) {
    "start" {
        Write-Host "Starting Quant AI Trader daemon..." -ForegroundColor Yellow
        try {
            Start-ScheduledTask -TaskName $TaskName
            Write-Host "  Task started" -ForegroundColor Green
            Start-Sleep -Seconds 10
            Show-Status
        } catch {
            Write-Host "  ERROR: $_" -ForegroundColor Red
            Write-Host "  Run install_daemon_win.ps1 first to register the task." -ForegroundColor Yellow
        }
    }
    "stop" {
        Write-Host "Stopping Quant AI Trader..." -ForegroundColor Yellow
        try {
            Stop-ScheduledTask -TaskName $TaskName
            Write-Host "  Task stopped" -ForegroundColor Green
        } catch {
            Write-Host "  WARNING: $_" -ForegroundColor Yellow
        }
        # Kill all related processes
        foreach ($port in @(8001, 5180)) {
            $conns = netstat -ano 2>$null | Select-String ":$port\s+.*LISTENING"
            foreach ($conn in $conns) {
                $p = ($conn -split '\s+')[-1]
                if ($p -match '^\d+$') {
                    Stop-Process -Id ([int]$p) -Force -ErrorAction SilentlyContinue
                }
            }
        }
        Get-Process -Name "python", "node" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
        Write-Host "  All processes killed" -ForegroundColor Green
    }
    "restart" {
        Write-Host "Restarting Quant AI Trader..." -ForegroundColor Yellow
        try {
            Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 3
            foreach ($port in @(8001, 5180)) {
                $conns = netstat -ano 2>$null | Select-String ":$port\s+.*LISTENING"
                foreach ($conn in $conns) {
                    $p = ($conn -split '\s+')[-1]
                    if ($p -match '^\d+$') { Stop-Process -Id ([int]$p) -Force -ErrorAction SilentlyContinue }
                }
            }
            Get-Process -Name "python", "node" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 3
            Start-ScheduledTask -TaskName $TaskName
            Write-Host "  Restarted" -ForegroundColor Green
            Start-Sleep -Seconds 10
            Show-Status
        } catch {
            Write-Host "  ERROR: $_" -ForegroundColor Red
        }
    }
    "status" {
        Show-Status
    }
    "logs" {
        Write-Host "Tailing daemon log (Ctrl+C to stop):" -ForegroundColor Yellow
        Write-Host ""
        Get-Content "$LogDir\daemon.log" -Wait -Tail 20
    }
}
