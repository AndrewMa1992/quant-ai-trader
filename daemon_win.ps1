# ═══════════════════════════════════════════════════════════════
# Quant AI Trader — Windows 守护进程 (PowerShell)
# 功能：启动/监控 Backend + Frontend + AutoTrader
#       health check → 自动重启 → 熔断冷却 → git pull → 代码变更检测
#
# 开机自启：通过 Windows 任务计划程序注册
# 被杀后自启：任务计划程序设置 1分钟间隔重启
# ═══════════════════════════════════════════════════════════════
$ErrorActionPreference = "Continue"
$host.UI.RawUI.WindowTitle = "QuantAI-Daemon"

# ═══════════════════════════════════════════════════════════════
# 路径配置
# ═══════════════════════════════════════════════════════════════
$ProjectRoot = "E:\workbuddyspace\Claw\quant-ai-trader"
$PythonBin  = "C:\Users\hshor\.workbuddy\binaries\python\versions\3.13.12\python.exe"
$PythonVenv = "$ProjectRoot\.venv_win\Scripts\python.exe"
$NodeRoot   = "C:\Users\hshor\.workbuddy\binaries\node\versions\22.22.2"
$NodeBin    = "$NodeRoot\node.exe"
$NpmBin     = "$NodeRoot\npm.cmd"
$NpmPrefix  = "C:\Users\hshor\.workbuddy\binaries\node\workspace"
$LogDir     = "$ProjectRoot\logs"
$DaemonLog  = "$LogDir\daemon.log"
$BackendLog = "$LogDir\backend.log"
$FrontendLog = "$LogDir\frontend.log"
$TraderLog  = "$LogDir\trader.log"

# 环境变量
$env:TORCH_HOME = "$ProjectRoot\cache\torch"
$env:HF_HOME    = "$ProjectRoot\cache\huggingface"
$env:SKIP_FINBERT_DOWNLOAD = "1"
$env:HF_HUB_DOWNLOAD_TIMEOUT = "15"
$env:PATH = "$NodeRoot;$env:PATH"

# ═══════════════════════════════════════════════════════════════
# 熔断参数
# ═══════════════════════════════════════════════════════════════
$MaxRetries     = 5
$CooldownSec    = 300
$CheckInterval  = 30

$BackendRetries  = 0
$FrontendRetries = 0
$TraderRetries   = 0
$GitPullCounter  = 0
$GitPushCounter  = 0
$CodeCheckCounter = 0

# ═══════════════════════════════════════════════════════════════
# 运行时选择（优先 venv，fallback 到系统 Python）
# ═══════════════════════════════════════════════════════════════
if (Test-Path $PythonVenv) {
    $PyExe = $PythonVenv
} elseif (Test-Path $PythonBin) {
    $PyExe = $PythonBin
} else {
    $PyExe = "python"
}
$VerbosePreference = "Continue"

# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

function Log {
    param([string]$Message)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $Message"
    Write-Host $line
    Add-Content -Path $DaemonLog -Value $line -Encoding UTF8
}

function Kill-Port {
    param([int]$Port)
    try {
        $conns = netstat -ano 2>$null | Select-String ":$Port\s+.*LISTENING"
        foreach ($conn in $conns) {
            $pidStr = ($conn -split '\s+')[-1]
            if ($pidStr -match '^\d+$') {
                Stop-Process -Id ([int]$pidStr) -Force -ErrorAction SilentlyContinue
                Log "  Killed stale process on :$Port (PID $pidStr)"
            }
        }
    } catch {}
}

function Kill-ProcessByName {
    param([string]$Name)
    Get-Process -Name $Name -ErrorAction SilentlyContinue | ForEach-Object {
        try {
            if ($_.CommandLine -match "run_backend|auto_trader|vite") {
                Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
                Log "  Killed $($_.ProcessName) (PID $($_.Id))"
            }
        } catch {}
    }
}

function Test-Backend {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:8001/health" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Test-Frontend {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:5180" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Test-TraderRunning {
    $p = Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -match "auto_trader" 2>$null
    }
    return ($null -ne $p -and $p.Count -gt 0)
}

function Invoke-Cooldown {
    param([string]$Name, [ref]$RetriesVar)
    if ($RetriesVar.Value -ge $MaxRetries) {
        Log "CRITICAL: ${Name} max retries ($MaxRetries) reached, cooling ${CooldownSec}s..."
        Start-Sleep -Seconds $CooldownSec
        $RetriesVar.Value = 0
    }
}

# ═══════════════════════════════════════════════════════════════
# 服务启动函数
# ═══════════════════════════════════════════════════════════════

function Start-Backend {
    if (Test-Backend) {
        $script:BackendRetries = 0
        return $true
    }

    Invoke-Cooldown "Backend" ([ref]$script:BackendRetries)
    Kill-Port 8001

    Log "Starting Backend (FastAPI :8001)..."
    try {
        $proc = Start-Process -FilePath $PyExe `
            -ArgumentList "run_backend.py" `
            -WorkingDirectory $ProjectRoot `
            -WindowStyle Hidden `
            -RedirectStandardOutput $BackendLog `
            -RedirectStandardError "$LogDir\backend_err.log" `
            -PassThru

        # 等待健康检查通过（最多 60 秒）
        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep -Seconds 2
            if (Test-Backend) {
                Log "  Backend ready (PID $($proc.Id))"
                $script:BackendRetries = 0
                return $true
            }
        }

        $script:BackendRetries++
        Log "  Backend failed to start (attempt $BackendRetries/$MaxRetries)"
        return $false
    } catch {
        $script:BackendRetries++
        Log "  Backend start error: $_"
        return $false
    }
}

function Start-Frontend {
    if (Test-Frontend) {
        $script:FrontendRetries = 0
        return $true
    }

    Invoke-Cooldown "Frontend" ([ref]$script:FrontendRetries)
    Kill-Port 5180

    Log "Starting Frontend (Vite :5180)..."
    try {
        $env:PATH = "$NodeRoot;$NpmPrefix\node_modules\.bin;$env:PATH"
        $env:NODE_PATH = "$NpmPrefix\node_modules"

        $proc = Start-Process -FilePath $NpmBin `
            -ArgumentList "run dev" `
            -WorkingDirectory "$ProjectRoot\frontend" `
            -WindowStyle Hidden `
            -RedirectStandardOutput $FrontendLog `
            -RedirectStandardError "$LogDir\frontend_err.log" `
            -PassThru

        # Vite 启动较慢
        for ($i = 0; $i -lt 20; $i++) {
            Start-Sleep -Seconds 2
            if (Test-Frontend) {
                Log "  Frontend ready (PID $($proc.Id))"
                $script:FrontendRetries = 0
                return $true
            }
        }

        $script:FrontendRetries++
        Log "  Frontend failed to start (attempt $FrontendRetries/$MaxRetries)"
        return $false
    } catch {
        $script:FrontendRetries++
        Log "  Frontend start error: $_"
        return $false
    }
}

function Start-Trader {
    if (Test-TraderRunning) {
        $script:TraderRetries = 0
        return $true
    }

    Invoke-Cooldown "AutoTrader" ([ref]$script:TraderRetries)

    Log "Starting Auto Trader (10min cycle)..."
    try {
        $proc = Start-Process -FilePath $PyExe `
            -ArgumentList "auto_trader.py --interval 600" `
            -WorkingDirectory $ProjectRoot `
            -WindowStyle Hidden `
            -RedirectStandardOutput $TraderLog `
            -RedirectStandardError "$LogDir\trader_err.log" `
            -PassThru

        Start-Sleep -Seconds 5

        if (Test-TraderRunning) {
            Log "  Auto Trader ready (PID $($proc.Id))"
            $script:TraderRetries = 0
            return $true
        }

        $script:TraderRetries++
        Log "  Auto Trader failed to start (attempt $TraderRetries/$MaxRetries)"
        return $false
    } catch {
        $script:TraderRetries++
        Log "  Auto Trader start error: $_"
        return $false
    }
}

# ═══════════════════════════════════════════════════════════════
# 代码变更检测
# ═══════════════════════════════════════════════════════════════

function Check-CodeChanges {
    # 检查后端代码变更
    $backChanged = $false
    $backendMarker = Get-Item $BackendLog -ErrorAction SilentlyContinue
    if ($backendMarker) {
        $lastBackTime = $backendMarker.LastWriteTime
        $changed = Get-ChildItem "$ProjectRoot\backend", "$ProjectRoot\api_gateway" `
            -Recurse -Filter "*.py" -ErrorAction SilentlyContinue | Where-Object {
                $_.LastWriteTime -gt $lastBackTime
            }
        if ($changed) {
            $backChanged = $true
            Log "Code change detected in Backend, restarting..."
            Kill-Port 8001
            Start-Backend
        }
    }

    # 检查交易代码变更
    $traderMarker = Get-Item $TraderLog -ErrorAction SilentlyContinue
    if ($traderMarker) {
        $lastTradeTime = $traderMarker.LastWriteTime
        $changed = Get-ChildItem "$ProjectRoot\backend\ai_models", `
            "$ProjectRoot\backend\trading_engine", `
            "$ProjectRoot\auto_trader.py" `
            -Recurse -Filter "*.py" -ErrorAction SilentlyContinue | Where-Object {
                $_.LastWriteTime -gt $lastTradeTime
            }
        if ($changed) {
            Log "Code change detected in Trader, restarting..."
            Kill-ProcessByName "python"
            Start-Sleep 2
            Start-Trader
        }
    }
}

# ═══════════════════════════════════════════════════════════════
# Git Pull
# ═══════════════════════════════════════════════════════════════

function Invoke-GitPull {
    try {
        Set-Location $ProjectRoot
        git fetch origin 2>&1 | Out-Null
        $behind = & git rev-list HEAD..origin/dev-20260522 --count 2>$null
        if ($behind -and [int]$behind -gt 0) {
            Log "Git: $behind new commit(s) from remote, pulling..."
            git pull --rebase origin dev-20260522 2>&1 | ForEach-Object { Log "Git: $_" }
            Log "Git: pull complete, restarting services to apply updates..."
            Kill-ProcessByName "python"
            Start-Sleep 2
            return $true  # 有更新
        }
        return $false  # 无更新
    } catch {
        return $false
    } finally {
        Set-Location $ProjectRoot
    }
}

# ═══════════════════════════════════════════════════════════════
# Git Auto-Commit + Push（每个迭代版本自动上传到 GitHub）
# ═══════════════════════════════════════════════════════════════

function Invoke-GitAutoPush {
    try {
        Set-Location $ProjectRoot
        # 检查是否有未提交的变更
        $status = git status --porcelain 2>$null
        if ($status) {
            $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
            $commitMsg = "auto: $ts — daemon cycle snapshot"
            git add -A 2>&1 | Out-Null
            git commit -m $commitMsg 2>&1 | Out-Null
            Log "Git: auto-commit — $commitMsg"
            # 推送到 GitHub
            git push origin dev-20260522 2>&1 | ForEach-Object { Log "Git push: $_" }
            Log "Git: push complete"
        }
    } catch {
        # 静默处理网络/Git 认证问题
    } finally {
        Set-Location $ProjectRoot
    }
}

# ═══════════════════════════════════════════════════════════════
# 清理函数（优雅退出）
# ═══════════════════════════════════════════════════════════════

function Cleanup {
    Log "═════ Daemon stopping, killing children ═════"
    Kill-Port 8001
    Kill-Port 5180
    Kill-ProcessByName "python"
    Start-Sleep -Seconds 2
    Log "═════ Daemon stopped ═════"
    exit 0
}

# 注册退出事件
$null = Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action { Cleanup }

# ═══════════════════════════════════════════════════════════════
# 主循环
# ═══════════════════════════════════════════════════════════════

function Main {
    # 确保日志目录存在
    if (-not (Test-Path $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    }

    # 写入 PID
    $pid | Set-Content "$LogDir\daemon.pid"

    Log "═══════════════════════════════════════════"
    Log "  Quant AI Trader — Daemon v3.0 (Windows)"
    Log "═══════════════════════════════════════════"
    Log "Project:  $ProjectRoot"
    Log "Python:   $PyExe"
    Log "Node:     $NodeBin"
    Log "PID:      $pid"
    Log "═══════════════════════════════════════════"

    # === 首次启动：Git Pull + 顺序启动 ===
    Log "Initial startup sequence..."
    Log "Git: fetching latest from remote..."
    try { Invoke-GitPull | Out-Null } catch {}
    
    $bk = Start-Backend
    Start-Sleep -Seconds 3
    $fe = Start-Frontend
    Start-Sleep -Seconds 3
    $tr = Start-Trader

    # === 持续监控循环 ===
    while ($true) {
        Start-Sleep -Seconds $CheckInterval

        # 健康检查 + 自动重启
        try { Start-Backend | Out-Null } catch {}
        try { Start-Frontend | Out-Null } catch {}
        try { Start-Trader | Out-Null } catch {}

        # 代码变更检测（每 60 秒）
        $script:CodeCheckCounter++
        if ($script:CodeCheckCounter -ge 2) {
            $script:CodeCheckCounter = 0
            try { Check-CodeChanges } catch {}
        }

        # Git Auto-Push（每 30 分钟自动提交并推送变更到 GitHub）
        $script:GitPushCounter++
        if ($script:GitPushCounter -ge 60) {
            try { Invoke-GitAutoPush } catch {}
            $script:GitPushCounter = 0
        }

        # Git Pull（每 10 分钟拉取远程更新并自动重启部署）
        $script:GitPullCounter++
        if ($script:GitPullCounter -ge 20) {
            try {
                $updated = Invoke-GitPull
                if ($updated) {
                    Start-Backend | Out-Null
                    Start-Sleep 3
                    Start-Trader | Out-Null
                }
            } catch {}
            $script:GitPullCounter = 0
        }
    }
}

# ═══════════════════════════════════════════════════════════════
# 执行
# ═══════════════════════════════════════════════════════════════
Main
