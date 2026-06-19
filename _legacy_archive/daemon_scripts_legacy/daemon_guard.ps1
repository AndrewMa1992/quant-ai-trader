# Quant AI Trader - 永久守护进程 (PowerShell版)
# 功能: 健康检查 + 自动重启 + Git同步 + 日志轮转
# 用法: powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File daemon_guard.ps1

$ErrorActionPreference = "Continue"
$host.UI.RawUI.WindowTitle = "QuantAI-Daemon-PS"

$Proj = "E:\workbuddyspace\Claw\quant-ai-trader"
$Py = "C:\Users\hshor\.workbuddy\binaries\python\versions\3.13.12\python.exe"
$Node = "C:\Users\hshor\.workbuddy\binaries\node\versions\22.22.2"
$Npm = "$Node\npm.cmd"
$NpmPrefix = "C:\Users\hshor\.workbuddy\binaries\node\workspace"

# 环境变量
$env:TORCH_HOME = "$Proj\cache\torch"
$env:HF_HOME = "$Proj\cache\huggingface"
$env:SKIP_FINBERT_DOWNLOAD = "1"
$env:HF_HUB_DOWNLOAD_TIMEOUT = "15"
$env:PATH = "$Node;$NpmPrefix\node_modules\.bin;$env:PATH"
$env:NODE_PATH = "$NpmPrefix\node_modules"

$CHECK_INTERVAL = 30
$GIT_PULL_EVERY = 20
$PUSH_INTERVAL = 10
$MAX_RETRIES = 5
$COOLDOWN_SEC = 300
$LOG_DIR = "$Proj\logs"

# 确保日志目录存在
if (!(Test-Path $LOG_DIR)) { New-Item -ItemType Directory -Path $LOG_DIR -Force | Out-Null }

function Write-Log {
    param([string]$msg)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $msg"
    Write-Host $line
    Add-Content -Path "$LOG_DIR\guard.log" -Value $line
}

function Test-Backend {
    try { $null = Invoke-WebRequest -Uri "http://localhost:8001/health" -TimeoutSec 5 -UseBasicParsing; return $true } catch { return $false }
}

function Test-Frontend {
    try { $null = Invoke-WebRequest -Uri "http://localhost:5180" -TimeoutSec 5 -UseBasicParsing; return $true } catch { return $false }
}

function Test-Trader {
    $procs = Get-Process python -ErrorAction SilentlyContinue | Where-Object {
        try { (Get-WmiObject Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine -match 'auto_trader' } catch { $false }
    }
    return ($procs -and $procs.Count -gt 0)
}

function Kill-Port {
    param([int]$port)
    $conns = netstat -ano 2>$null | Select-String ":$port\s+.*LISTENING"
    foreach ($conn in $conns) {
        $pid = ($conn -split '\s+')[-1]
        if ($pid -match '^\d+$') {
            Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        }
    }
}

function Start-Backend {
    Kill-Port 8001
    Start-Process -FilePath $Py -ArgumentList "$Proj\run_backend.py" -WorkingDirectory $Proj -WindowStyle Minimized
    Start-Sleep -Seconds 5
}

function Start-Frontend {
    Kill-Port 5180
    Start-Process -FilePath $Npm -ArgumentList "run", "dev" -WorkingDirectory "$Proj\frontend" -WindowStyle Minimized
    Start-Sleep -Seconds 3
}

function Start-Trader {
    Start-Process -FilePath $Py -ArgumentList "$Proj\auto_trader.py", "--interval", "600" -WorkingDirectory $Proj -WindowStyle Minimized
    Start-Sleep -Seconds 3
}

function Do-GitSync {
    try {
        Set-Location $Proj
        git stash 2>&1 | Out-Null
        $behind = (git rev-list HEAD..origin/dev-20260522 --count 2>$null)
        if ($behind -gt 0) {
            Write-Log "Git: $behind new commits - pulling and restarting..."
            git pull --rebase origin dev-20260522 2>&1 | Out-Null
            Kill-Port 8001
            Kill-Port 5180
            Start-Sleep -Seconds 2
            Start-Backend
            Start-Frontend
            Start-Trader
            Write-Log "Git: updated and services restarted"
        }
        Set-Location $Proj
    } catch {
        Write-Log "Git sync failed: $_"
    }
}

function Do-GitAutoPush {
    try {
        Set-Location $Proj
        $status = git status --porcelain 2>$null
        if ($status) {
            $count = ($status -split "`n").Count
            $commitMsg = "auto: daemon guard commit $(Get-Date -Format 'yyyyMMdd-HHmmss')"
            git add -A 2>&1 | Out-Null
            git commit -m $commitMsg 2>&1 | Out-Null
            git push origin dev-20260522 2>&1 | Out-Null
            Write-Log "GitPush: $count file(s) committed & pushed → dev-20260522"
        }
        Set-Location $Proj
    } catch {
        Write-Log "Git push failed: $_"
    }
}

function Rotate-Log {
    param([string]$logFile)
    if (Test-Path $logFile) {
        $size = (Get-Item $logFile).Length
        if ($size -gt 50MB) {
            Move-Item $logFile "$logFile.bak" -Force
            Write-Log "Log rotated: $logFile ($($size/1MB)MB)"
        }
    }
}

# ===== 主循环 =====
Write-Log "============================================"
Write-Log "  Quant AI Trader - PowerShell Daemon v1.0"
Write-Log "  工作目录: $Proj"
Write-Log "  每${CHECK_INTERVAL}s健康检查"
Write-Log "============================================"

# 首次Git同步
Write-Log "Git: syncing latest code..."
Do-GitSync

$cycleCount = 0
$pushCycleCount = 0
$backendRetries = 0
$frontendRetries = 0

while ($true) {
    Start-Sleep -Seconds $CHECK_INTERVAL
    $cycleCount++
    $pushCycleCount++
    
    # Git 同步
    if ($cycleCount % $GIT_PULL_EVERY -eq 0) {
        Do-GitSync
    }
    
    # Git 自动 Push (每 PUSH_INTERVAL 轮检查一次)
    if ($pushCycleCount % $PUSH_INTERVAL -eq 0) {
        Do-GitAutoPush
    }
    
    # 后端健康检查
    if (-not (Test-Backend)) {
        Write-Log "BACKEND DOWN - restarting (retry $backendRetries/$MAX_RETRIES)..."
        $backendRetries++
        if ($backendRetries -ge $MAX_RETRIES) {
            Write-Log "BACKEND max retries - cooling ${COOLDOWN_SEC}s..."
            Start-Sleep -Seconds $COOLDOWN_SEC
            $backendRetries = 0
        }
        Start-Backend
    } else {
        $backendRetries = 0
    }
    
    # 前端健康检查
    if (-not (Test-Frontend)) {
        Write-Log "FRONTEND DOWN - restarting (retry $frontendRetries/$MAX_RETRIES)..."
        $frontendRetries++
        if ($frontendRetries -ge $MAX_RETRIES) {
            Write-Log "FRONTEND max retries - cooling ${COOLDOWN_SEC}s..."
            Start-Sleep -Seconds $COOLDOWN_SEC
            $frontendRetries = 0
        }
        Start-Frontend
    } else {
        $frontendRetries = 0
    }
    
    # Auto Trader 检查
    if (-not (Test-Trader)) {
        Write-Log "TRADER DOWN - restarting..."
        Start-Trader
    }
    
    # 日志轮转 (每50轮)
    if ($cycleCount % 50 -eq 0) {
        Rotate-Log "$LOG_DIR\backend.log"
        Rotate-Log "$LOG_DIR\trader.log"
        Rotate-Log "$LOG_DIR\guard.log"
    }
    
    # 每小时输出状态摘要
    if ($cycleCount % 120 -eq 0) {
        $mem = Get-Process python -ErrorAction SilentlyContinue | Measure-Object -Property WorkingSet64 -Sum
        $memMB = [math]::Round($mem.Sum / 1MB, 1)
        Write-Log "HOURLY STATUS: Python mem=${memMB}MB, Backend=$(Test-Backend), Frontend=$(Test-Frontend), Trader=$(Test-Trader)"
    }
}
