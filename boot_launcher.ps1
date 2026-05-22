# Quant AI Trader - 开机自启动脚本
# 功能：拉取最新代码 → 停止旧进程 → 启动全栈
$ErrorActionPreference = "Stop"
$ProjectRoot = "G:\workbuddyspace\Claw\quant-ai-trader"

# 环境变量
$env:TORCH_HOME = "$ProjectRoot\cache\torch"
$env:HF_HOME = "$ProjectRoot\cache\huggingface"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Quant AI Trader - Boot Launcher" -ForegroundColor Cyan
Write-Host "  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# ============================================================
# Step 1: 拉取最新代码
# ============================================================
Write-Host "[1/4] Pulling latest code..." -ForegroundColor Yellow
Set-Location $ProjectRoot

try {
    # Stash local changes, pull, then try to restore
    $hasLocal = (git status --porcelain 2>$null).Length -gt 0
    if ($hasLocal) {
        git stash push -m "auto-stash-$(Get-Date -Format 'yyyyMMdd-HHmmss')" 2>&1 | Out-Null
        Write-Host "  Stashed local changes" -ForegroundColor Gray
    }
    
    git fetch origin dev-20260522 2>&1 | Out-Null
    $behind = (git rev-list HEAD..origin/dev-20260522 --count 2>$null)
    
    if ($behind -gt 0) {
        Write-Host "  Found $behind new commit(s), pulling..." -ForegroundColor Green
        git pull --rebase origin dev-20260522 2>&1
        Write-Host "  Code updated to latest ✓" -ForegroundColor Green
        
        # Restore stash if there was one
        if ($hasLocal) {
            git stash pop 2>&1 | Out-Null
            Write-Host "  Local changes restored" -ForegroundColor Gray
        }
    } else {
        Write-Host "  Already up to date ✓" -ForegroundColor Green
    }
} catch {
    Write-Host "  Git pull failed: $_" -ForegroundColor Red
    Write-Host "  Continuing with current code..." -ForegroundColor Yellow
}

# ============================================================
# Step 2: 安装/更新依赖（如需要）
# ============================================================
Write-Host "[2/4] Checking dependencies..." -ForegroundColor Yellow

$pkgHashFile = "$ProjectRoot\frontend\.pkg-hash"
$currentHash = (Get-FileHash "$ProjectRoot\frontend\package.json" -Algorithm MD5).Hash

$needInstall = $false
if (Test-Path $pkgHashFile) {
    $storedHash = Get-Content $pkgHashFile
    if ($storedHash -ne $currentHash) {
        $needInstall = $true
    }
} else {
    $needInstall = $true
}

if ($needInstall) {
    Write-Host "  Installing frontend dependencies..." -ForegroundColor Green
    Set-Location "$ProjectRoot\frontend"
    npm install --silent 2>&1 | Out-Null
    $currentHash | Set-Content $pkgHashFile
    Write-Host "  Dependencies updated ✓" -ForegroundColor Green
} else {
    Write-Host "  Dependencies up to date ✓" -ForegroundColor Green
}

# ============================================================
# Step 3: 停止旧进程
# ============================================================
Write-Host "[3/4] Stopping old processes..." -ForegroundColor Yellow

# 通过端口占用找到并杀掉旧进程
$ports = @(8001, 5180)
foreach ($port in $ports) {
    $conns = netstat -ano 2>$null | Select-String ":$port\s+.*LISTENING"
    foreach ($conn in $conns) {
        $pid = ($conn -split '\s+')[-1]
        if ($pid -match '^\d+$') {
            try {
                Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
                Write-Host "  Killed process PID $pid on port $port" -ForegroundColor Gray
            } catch {}
        }
    }
}
Start-Sleep -Seconds 2
Write-Host "  Cleanup done ✓" -ForegroundColor Green

# ============================================================
# Step 4: 启动全栈服务
# ============================================================
Write-Host "[4/4] Starting services..." -ForegroundColor Yellow

Set-Location $ProjectRoot

# 后端 FastAPI
Start-Process python -ArgumentList "run_backend.py" -WorkingDirectory $ProjectRoot -WindowStyle Minimized
Write-Host "  Backend launching on :8001" -ForegroundColor Green

# 等待后端就绪
Write-Host "  Waiting for backend..." -ForegroundColor Gray
$maxWait = 60
for ($i = 0; $i -lt $maxWait; $i++) {
    try {
        $null = Invoke-WebRequest -Uri "http://localhost:8001/health" -TimeoutSec 2 -UseBasicParsing
        Write-Host "  Backend ready ✓" -ForegroundColor Green
        break
    } catch {
        Start-Sleep -Seconds 2
    }
}

# 前端 Vite
Start-Process npm -ArgumentList "run dev" -WorkingDirectory "$ProjectRoot\frontend" -WindowStyle Minimized
Write-Host "  Frontend launching on :5180" -ForegroundColor Green

# 自动交易引擎（延迟5秒等前端就绪）
Start-Sleep -Seconds 5
Start-Process python -ArgumentList "auto_trader.py --interval 1800" -WorkingDirectory $ProjectRoot -WindowStyle Minimized
Write-Host "  Auto Trader launching (30min cycle)" -ForegroundColor Green

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Quant AI Trader - All Systems Go" -ForegroundColor Cyan
Write-Host "  Web UI:   http://localhost:5180" -ForegroundColor White
Write-Host "  Backend:  http://localhost:8001" -ForegroundColor White
Write-Host "  API Docs: http://localhost:8001/docs" -ForegroundColor White
Write-Host "============================================" -ForegroundColor Cyan
