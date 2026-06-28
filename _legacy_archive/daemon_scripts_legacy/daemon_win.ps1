# ═══════════════════════════════════════════════════════════════
# Quant AI Trader v2 — Windows 守护进程 (PowerShell)
# 功能：启动/监控 API Gateway + 6 Microservices + Frontend + TradingPipeline
#       health check → 自动重启 → 熔断冷却 → git pull → 代码变更检测
#
# 开机自启：通过 Windows 任务计划程序注册
# 被杀后自启：任务计划程序设置 1分钟间隔重启
# ═══════════════════════════════════════════════════════════════
$ErrorActionPreference = "Continue"
$host.UI.RawUI.WindowTitle = "QuantAI-v2-Daemon"

# ═══════════════════════════════════════════════════════════════
# 路径配置（$PSScriptRoot = 脚本自身所在目录，消除硬编码）
# ═══════════════════════════════════════════════════════════════
$ProjectRoot = $PSScriptRoot
$PythonBin  = "C:\Users\hshor\.workbuddy\binaries\python\versions\3.13.12\python.exe"
$PythonVenv = "$ProjectRoot\.venv_win\Scripts\python.exe"
$NodeRoot   = "C:\Users\hshor\.workbuddy\binaries\node\versions\22.22.2"
$NodeBin    = "$NodeRoot\node.exe"
$NpmBin     = "$NodeRoot\npm.cmd"
$NpmPrefix  = "C:\Users\hshor\.workbuddy\binaries\node\workspace"
$LogDir     = "$ProjectRoot\logs"
$DaemonLog  = "$LogDir\daemon.log"
$ApiLog     = "$LogDir\api_gateway.log"
$FrontendLog = "$LogDir\frontend.log"
$PipelineLog = "$LogDir\pipeline.log"

# v2 微服务日志
$DataSvcLog    = "$LogDir\data_service.log"
$FactorSvcLog  = "$LogDir\factor_service.log"
$TrainSvcLog   = "$LogDir\model_train.log"
$InferSvcLog   = "$LogDir\model_infer.log"
$RiskSvcLog    = "$LogDir\risk_service.log"
$ExecSvcLog    = "$LogDir\execution_service.log"

# v2 端口（与 configs/settings.py 保持同步）
$ApiPort  = 8001
$DataPort = 8011
$FactorPort = 8012
$TrainPort  = 8013
$InferPort  = 8014
$RiskPort   = 8015
$ExecPort   = 8016
$FrontendPort = 5180

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

$ApiRetries       = 0
$FrontendRetries  = 0
$PipelineRetries  = 0
$DataSvcRetries   = 0
$FactorSvcRetries = 0
$TrainSvcRetries  = 0
$InferSvcRetries  = 0
$RiskSvcRetries   = 0
$ExecSvcRetries   = 0
$GitPullCounter   = 0
$GitPushCounter   = 0
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
            if ($_.CommandLine -match "api_gateway|trading_pipeline|uvicorn.*services\.|vite") {
                Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
                Log "  Killed $($_.ProcessName) (PID $($_.Id))"
            }
        } catch {}
    }
}

# ── v2 健康检查函数 ────────────────────────────────────────────

function Test-ApiGateway {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:$ApiPort/health" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

function Test-Microservice {
    param([int]$Port, [string]$SvcName)
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:$Port/health" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

function Test-Frontend {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:$FrontendPort" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

function Test-PipelineRunning {
    $p = Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -match "trading_pipeline" 2>$null
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
# v2 服务启动函数
# ═══════════════════════════════════════════════════════════════

function Start-ApiGateway {
    if (Test-ApiGateway) {
        $script:ApiRetries = 0
        return $true
    }

    Invoke-Cooldown "API Gateway" ([ref]$script:ApiRetries)
    Kill-Port $ApiPort

    Log "Starting API Gateway (uvicorn api_gateway.main:app :$ApiPort)..."
    try {
        $proc = Start-Process -NoNewWindow -FilePath $PyExe `
            -ArgumentList "-m uvicorn api_gateway.main:app --host 0.0.0.0 --port $ApiPort" `
            -WorkingDirectory $ProjectRoot `
            -RedirectStandardOutput $ApiLog `
            -RedirectStandardError "$LogDir\api_gateway_err.log" `
            -PassThru

        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep -Seconds 2
            if (Test-ApiGateway) {
                Log "  API Gateway ready (PID $($proc.Id))"
                $script:ApiRetries = 0
                return $true
            }
        }

        $script:ApiRetries++
        Log "  API Gateway failed to start (attempt $ApiRetries/$MaxRetries)"
        return $false
    } catch {
        $script:ApiRetries++
        Log "  API Gateway start error: $_"
        return $false
    }
}

function Start-Microservice {
    param([string]$Module, [int]$Port, [string]$Name, [string]$LogFile, [ref]$RetriesVar)

    if (Test-Microservice -Port $Port -SvcName $Name) {
        $RetriesVar.Value = 0
        return $true
    }

    Invoke-Cooldown $Name ([ref]$RetriesVar)
    Kill-Port $Port

    Log "Starting $Name (uvicorn $Module :$Port)..."
    try {
        $proc = Start-Process -NoNewWindow -FilePath $PyExe `
            -ArgumentList "-m uvicorn $Module --host 0.0.0.0 --port $Port" `
            -WorkingDirectory $ProjectRoot `
            -RedirectStandardOutput $LogFile `
            -RedirectStandardError "$LogDir\${Name}_err.log" `
            -PassThru

        for ($i = 0; $i -lt 15; $i++) {
            Start-Sleep -Seconds 2
            if (Test-Microservice -Port $Port -SvcName $Name) {
                Log "  $Name ready (PID $($proc.Id))"
                $RetriesVar.Value = 0
                return $true
            }
        }

        $RetriesVar.Value++
        Log "  $Name failed to start (attempt $($RetriesVar.Value)/$MaxRetries)"
        return $false
    } catch {
        $RetriesVar.Value++
        Log "  $Name start error: $_"
        return $false
    }
}

function Start-DataService       { Start-Microservice "services.data_service.main:app"        $DataPort   "data_service"     $DataSvcLog    ([ref]$script:DataSvcRetries) }
function Start-FactorService     { Start-Microservice "services.factor_service.main:app"       $FactorPort "factor_service"   $FactorSvcLog  ([ref]$script:FactorSvcRetries) }
function Start-TrainService      { Start-Microservice "services.model_train_service.main:app"  $TrainPort  "model_train"      $TrainSvcLog   ([ref]$script:TrainSvcRetries) }
function Start-InferService      { Start-Microservice "services.model_infer_service.main:app"  $InferPort  "model_infer"      $InferSvcLog   ([ref]$script:InferSvcRetries) }
function Start-RiskService       { Start-Microservice "services.risk_service.main:app"         $RiskPort   "risk_service"     $RiskSvcLog    ([ref]$script:RiskSvcRetries) }
function Start-ExecutionService  { Start-Microservice "services.execution_service.main:app"    $ExecPort   "execution_service" $ExecSvcLog    ([ref]$script:ExecSvcRetries) }

function Start-Frontend {
    if (Test-Frontend) {
        $script:FrontendRetries = 0
        return $true
    }

    Invoke-Cooldown "Frontend" ([ref]$script:FrontendRetries)
    Kill-Port $FrontendPort

    Log "Starting Frontend (Vite :$FrontendPort)..."
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

function Start-TradingPipeline {
    if (Test-PipelineRunning) {
        $script:PipelineRetries = 0
        return $true
    }

    Invoke-Cooldown "TradingPipeline" ([ref]$script:PipelineRetries)

    Log "Starting Trading Pipeline (trading_pipeline.py --interval $Interval)..."
    try {
        $proc = Start-Process -NoNewWindow -FilePath $PyExe `
            -ArgumentList "trading_pipeline.py --interval $Interval" `
            -WorkingDirectory $ProjectRoot `
            -RedirectStandardOutput $PipelineLog `
            -RedirectStandardError "$LogDir\pipeline_err.log" `
            -PassThru

        Start-Sleep -Seconds 5

        if (Test-PipelineRunning) {
            Log "  Trading Pipeline ready (PID $($proc.Id))"
            $script:PipelineRetries = 0
            return $true
        }

        $script:PipelineRetries++
        Log "  Trading Pipeline failed to start (attempt $PipelineRetries/$MaxRetries)"
        return $false
    } catch {
        $script:PipelineRetries++
        Log "  Trading Pipeline start error: $_"
        return $false
    }
}

# ═══════════════════════════════════════════════════════════════
# v2 状态展示
# ═══════════════════════════════════════════════════════════════

function Show-Status {
    Log "═══════════════════════════════════════════"
    Log "  v2 服务状态检查"
    Log "═══════════════════════════════════════════"

    $apiOk   = Test-ApiGateway
    $dataOk  = Test-Microservice -Port $DataPort -SvcName "data"
    $facOk   = Test-Microservice -Port $FactorPort -SvcName "factor"
    $trnOk   = Test-Microservice -Port $TrainPort -SvcName "train"
    $infOk   = Test-Microservice -Port $InferPort -SvcName "infer"
    $riskOk  = Test-Microservice -Port $RiskPort -SvcName "risk"
    $execOk  = Test-Microservice -Port $ExecPort -SvcName "exec"
    $feOk    = Test-Frontend
    $pipeOk  = Test-PipelineRunning

    Log ("  API Gateway     :$ApiPort    — " + $(if ($apiOk)  {"UP"} else {"DOWN"}))
    Log ("  Data Service    :$DataPort   — " + $(if ($dataOk)  {"UP"} else {"DOWN"}))
    Log ("  Factor Service  :$FactorPort   — " + $(if ($facOk)  {"UP"} else {"DOWN"}))
    Log ("  Model Train     :$TrainPort   — " + $(if ($trnOk)  {"UP"} else {"DOWN"}))
    Log ("  Model Infer     :$InferPort   — " + $(if ($infOk)  {"UP"} else {"DOWN"}))
    Log ("  Risk Service    :$RiskPort   — " + $(if ($riskOk)  {"UP"} else {"DOWN"}))
    Log ("  Execution Svc   :$ExecPort   — " + $(if ($execOk)  {"UP"} else {"DOWN"}))
    Log ("  Frontend (Vite) :$FrontendPort  — " + $(if ($feOk)    {"UP"} else {"DOWN"}))
    Log ("  TradingPipeline — " + $(if ($pipeOk) {"RUNNING"} else {"STOPPED"}))
    Log "═══════════════════════════════════════════"
}

# ═══════════════════════════════════════════════════════════════
# 代码变更检测（v2 路径）
# ═══════════════════════════════════════════════════════════════

function Check-CodeChanges {
    $apiMarker = Get-Item $ApiLog -ErrorAction SilentlyContinue
    if ($apiMarker) {
        $lastTime = $apiMarker.LastWriteTime
        $changed = Get-ChildItem "$ProjectRoot\api_gateway", "$ProjectRoot\services", "$ProjectRoot\configs" `
            -Recurse -Filter "*.py" -ErrorAction SilentlyContinue | Where-Object {
                $_.LastWriteTime -gt $lastTime
            }
        if ($changed) {
            Log "Code change detected in v2 services, restarting..."
            Kill-Port $ApiPort
            Kill-Port $DataPort
            Kill-Port $FactorPort
            Kill-Port $TrainPort
            Kill-Port $InferPort
            Kill-Port $RiskPort
            Kill-Port $ExecPort
            Start-ApiGateway
            Start-Sleep -Seconds 3
            Start-AllMicroservices
        }
    }

    $pipeMarker = Get-Item $PipelineLog -ErrorAction SilentlyContinue
    if ($pipeMarker) {
        $lastPipeTime = $pipeMarker.LastWriteTime
        $changed = Get-ChildItem "$ProjectRoot\trading_pipeline.py", "$ProjectRoot\shared", `
            "$ProjectRoot\services\execution_service\live" `
            -Recurse -Filter "*.py" -ErrorAction SilentlyContinue | Where-Object {
                $_.LastWriteTime -gt $lastPipeTime
            }
        if ($changed) {
            Log "Code change detected in Pipeline, restarting..."
            Kill-ProcessByName "python"
            Start-Sleep 2
            Start-TradingPipeline
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
            return $true
        }
        return $false
    } catch {
        return $false
    } finally {
        Set-Location $ProjectRoot
    }
}

# ═══════════════════════════════════════════════════════════════
# Git Auto-Commit + Push
# ═══════════════════════════════════════════════════════════════

function Invoke-GitAutoPush {
    try {
        Set-Location $ProjectRoot
        $status = git status --porcelain 2>$null
        if ($status) {
            $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
            $commitMsg = "auto: $ts — daemon cycle snapshot"
            git add -A 2>&1 | Out-Null
            git commit -m $commitMsg 2>&1 | Out-Null
            Log "Git: auto-commit — $commitMsg"
            git push origin dev-20260522 2>&1 | ForEach-Object { Log "Git push: $_" }
            Log "Git: push complete"
        }
    } catch {}
    finally {
        Set-Location $ProjectRoot
    }
}

# ═══════════════════════════════════════════════════════════════
# 批量微服务启动
# ═══════════════════════════════════════════════════════════════

function Start-AllMicroservices {
    Start-DataService      | Out-Null
    Start-Sleep -Seconds 2
    Start-FactorService    | Out-Null
    Start-Sleep -Seconds 2
    Start-TrainService     | Out-Null
    Start-Sleep -Seconds 2
    Start-InferService     | Out-Null
    Start-Sleep -Seconds 2
    Start-RiskService      | Out-Null
    Start-Sleep -Seconds 2
    Start-ExecutionService | Out-Null
}

# ═══════════════════════════════════════════════════════════════
# 清理函数（优雅退出）
# ═══════════════════════════════════════════════════════════════

function Cleanup {
    Log "═════ Daemon stopping, killing children ═════"
    Kill-Port $ApiPort
    Kill-Port $DataPort
    Kill-Port $FactorPort
    Kill-Port $TrainPort
    Kill-Port $InferPort
    Kill-Port $RiskPort
    Kill-Port $ExecPort
    Kill-Port $FrontendPort
    Kill-ProcessByName "python"
    Start-Sleep -Seconds 2
    Log "═════ Daemon stopped ═════"
    exit 0
}

$null = Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action { Cleanup }

# ═══════════════════════════════════════════════════════════════
# 主循环
# ═══════════════════════════════════════════════════════════════

function Main {
    if (-not (Test-Path $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    }

    $pid | Set-Content "$LogDir\daemon.pid"

    Log "═══════════════════════════════════════════"
    Log "  Quant AI Trader v2 — Daemon (Windows)"
    Log "═══════════════════════════════════════════"
    Log "Project:  $ProjectRoot"
    Log "Python:   $PyExe"
    Log "Node:     $NodeBin"
    Log "PID:      $pid"
    Log "═══════════════════════════════════════════"

    # === 首次启动：Git Pull + 顺序启动所有 v2 服务 ===
    Log "Initial startup sequence..."
    Log "Git: fetching latest from remote..."
    try { Invoke-GitPull | Out-Null } catch {}

    $apiOk = Start-ApiGateway
    Start-Sleep -Seconds 3

    # 启动 6 个微服务
    Start-AllMicroservices
    Start-Sleep -Seconds 3

    # 启动前端
    $feOk = Start-Frontend
    Start-Sleep -Seconds 3

    # 启动交易管线
    $pipeOk = Start-TradingPipeline

    # 展示初始状态
    Show-Status

    # === 持续监控循环 ===
    while ($true) {
        Start-Sleep -Seconds $CheckInterval

        # 健康检查 + 自动重启
        try { Start-ApiGateway       | Out-Null } catch {}
        try { Start-DataService      | Out-Null } catch {}
        try { Start-FactorService    | Out-Null } catch {}
        try { Start-TrainService     | Out-Null } catch {}
        try { Start-InferService     | Out-Null } catch {}
        try { Start-RiskService      | Out-Null } catch {}
        try { Start-ExecutionService | Out-Null } catch {}
        try { Start-Frontend         | Out-Null } catch {}
        try { Start-TradingPipeline  | Out-Null } catch {}

        # 状态展示（每 10 轮 ~5 min）
        $script:CodeCheckCounter++
        if ($script:CodeCheckCounter % 10 -eq 0) {
            Show-Status
        }

        # 代码变更检测（每 2 轮 ~60s）
        if ($script:CodeCheckCounter % 2 -eq 0) {
            try { Check-CodeChanges } catch {}
        }

        # Git Auto-Push（每 30 分钟）
        $script:GitPushCounter++
        if ($script:GitPushCounter -ge 60) {
            try { Invoke-GitAutoPush } catch {}
            $script:GitPushCounter = 0
        }

        # Git Pull（每 10 分钟拉取远程更新）
        $script:GitPullCounter++
        if ($script:GitPullCounter -ge 20) {
            try {
                $updated = Invoke-GitPull
                if ($updated) {
                    Start-ApiGateway | Out-Null
                    Start-Sleep 3
                    Start-AllMicroservices
                    Start-Sleep 3
                    Start-TradingPipeline | Out-Null
                }
            } catch {}
            $script:GitPullCounter = 0
        }
    }
}

# ═══════════════════════════════════════════════════════════════
# 执行
# ═══════════════════════════════════════════════════════════════
$Interval = 300
Main
