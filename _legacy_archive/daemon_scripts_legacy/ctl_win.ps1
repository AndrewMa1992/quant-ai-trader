# ═══════════════════════════════════════════════════════════════
# Quant AI Trader v2 — Windows 服务控制脚本
# 用法: .\ctl_win.ps1 {start|stop|restart|status|logs}
# ═══════════════════════════════════════════════════════════════
param(
    [ValidateSet("start", "stop", "restart", "status", "logs")]
    [string]$Action = "status"
)

$ScriptRoot = $PSScriptRoot
$ProjectRoot = $ScriptRoot
$LogDir = Join-Path $ProjectRoot "logs"

# v2 微服务端口定义
$ServicePorts = @{
    "api_gateway"  = 8001
    "data"         = 8011
    "factor"       = 8012
    "model_train"  = 8013
    "model_infer"  = 8014
    "risk"         = 8015
    "execution"    = 8016
}

# ── 辅助函数 ──────────────────────────────────────────────
function Test-PortListening {
    param([int]$Port)
    try {
        $conn = netstat -ano 2>$null | Select-String ":$Port\s+.*LISTENING"
        return $conn -ne $null
    } catch {
        return $false
    }
}

function Get-ProcessOnPort {
    param([int]$Port)
    try {
        $conns = netstat -ano 2>$null | Select-String ":$Port\s+.*LISTENING"
        $pids = @()
        foreach ($conn in $conns) {
            $pidStr = ($conn -split '\s+')[-1]
            if ($pidStr -match '^\d+$') {
                $pids += [int]$pidStr
            }
        }
        return $pids
    } catch {
        return @()
    }
}

function Stop-ServiceProcesses {
    Write-Host "Stopping all Quant AI Trader processes..." -ForegroundColor Yellow

    # 1. Kill processes on known ports
    foreach ($port in $ServicePorts.Values) {
        $pids = Get-ProcessOnPort -Port $port
        foreach ($pid in $pids) {
            Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
            Write-Host "  Stopped process on port ${port} (PID $pid)" -ForegroundColor Gray
        }
    }

    # 2. Kill remaining Python processes matching uvicorn / trading_pipeline
    $procs = Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object {
        $cmd = $_.CommandLine
        ($cmd -match "uvicorn" -or $cmd -match "trading_pipeline") 2>$null
    }
    foreach ($p in $procs) {
        Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
        Write-Host "  Stopped process: $($p.ProcessName) (PID $($p.Id))" -ForegroundColor Gray
    }

    Write-Host "All known services stopped." -ForegroundColor Green
}

function Show-Status {
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "  Quant AI Trader v2 — 微服务状态" -ForegroundColor Cyan
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host ""

    foreach ($svc in $ServicePorts.GetEnumerator() | Sort-Object Value) {
        $name = $svc.Key
        $port = $svc.Value
        $running = Test-PortListening -Port $port

        $color = if ($running) { "Green" } else { "Red" }
        $statusText = if ($running) { "RUNNING" } else { "DOWN" }

        $padding = " " * (20 - $name.Length)
        Write-Host "  ${name}${padding}:${port}  ${statusText}" -ForegroundColor $color
    }

    Write-Host ""
    Write-Host "  Web UI:   http://localhost:5180" -ForegroundColor White
    Write-Host "  API Docs: http://localhost:8001/docs" -ForegroundColor White
    Write-Host "  API Health: http://localhost:8001/health" -ForegroundColor White
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host ""
}

function Show-Logs {
    param([int]$TailLines = 20)
    Write-Host "Showing latest logs from $LogDir (Ctrl+C to stop):" -ForegroundColor Yellow
    Write-Host ""

    $latestLog = Get-ChildItem -Path $LogDir -Filter "qat_*.log" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if ($latestLog) {
        Get-Content $latestLog.FullName -Wait -Tail $TailLines
    } else {
        # Fall back to any recent log
        $anyLog = Get-ChildItem -Path $LogDir -Filter "*.log" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if ($anyLog) {
            Get-Content $anyLog.FullName -Wait -Tail $TailLines
        } else {
            Write-Host "No log files found in $LogDir" -ForegroundColor Red
        }
    }
}

# ── 命令分发 ──────────────────────────────────────────────
switch ($Action) {
    "start" {
        Write-Host "Starting Quant AI Trader v2 services..." -ForegroundColor Yellow
        Write-Host "Project root: $ProjectRoot" -ForegroundColor Gray

        $services = @(
            @{Name="api-gateway"; Port=8001; Module="api_gateway.main:app"},
            @{Name="data"; Port=8011; Module="services.data_service.main:app"},
            @{Name="factor"; Port=8012; Module="services.factor_service.main:app"},
            @{Name="model-train"; Port=8013; Module="services.model_train_service.main:app"},
            @{Name="model-infer"; Port=8014; Module="services.model_infer_service.main:app"},
            @{Name="risk"; Port=8015; Module="services.risk_service.main:app"},
            @{Name="execution"; Port=8016; Module="services.execution_service.main:app"}
        )

        foreach ($svc in $services) {
            if (Test-PortListening -Port $svc.Port) {
                Write-Host "  [SKIP] $($svc.Name) :$($svc.Port) already running" -ForegroundColor Yellow
                continue
            }
            Write-Host "  Starting $($svc.Name) on port $($svc.Port)..." -ForegroundColor Cyan
            Start-Process -NoNewWindow python -ArgumentList "-m", "uvicorn", $svc.Module, "--host", "0.0.0.0", "--port", $svc.Port
            Start-Sleep -Milliseconds 500
        }
        Start-Sleep -Seconds 3
        Show-Status
    }
    "stop" {
        Stop-ServiceProcesses
    }
    "restart" {
        Write-Host "Restarting Quant AI Trader v2..." -ForegroundColor Yellow
        Stop-ServiceProcesses
        Start-Sleep -Seconds 3
        & $PSCommandPath "start"
    }
    "status" {
        Show-Status
    }
    "logs" {
        Show-Logs
    }
}
