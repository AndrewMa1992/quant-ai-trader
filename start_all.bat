@echo off
chcp 65001 >nul
title QuantAI-StartAll

set "PROJ=E:\workbuddyspace\Claw\quant-ai-trader"
set "PY=C:\Users\hshor\.workbuddy\binaries\python\versions\3.13.12\python.exe"
set "NODE=C:\Users\hshor\.workbuddy\binaries\node\versions\22.22.2\node.exe"
set "NPM=C:\Users\hshor\.workbuddy\binaries\node\versions\22.22.2\npm.cmd"
set "NPM_PREFIX=C:\Users\hshor\.workbuddy\binaries\node\workspace"
set "LOG=%PROJ%\logs"

if not exist "%LOG%" mkdir "%LOG%"

echo ============================================
echo  Quant AI Trader - 全服务启动
echo ============================================
echo 项目: %PROJ%
echo Python: %PY%
echo Node: %NODE%
echo ============================================

:: 设置环境变量
set TORCH_HOME=%PROJ%\cache\torch
set HF_HOME=%PROJ%\cache\huggingface
set SKIP_FINBERT_DOWNLOAD=1
set HF_HUB_DOWNLOAD_TIMEOUT=15
set PATH=%NODE%;%NPM_PREFIX%\node_modules\.bin;%PATH%

:: 清理旧进程
echo [1/4] 清理旧进程...
taskkill /FI "WINDOWTITLE eq QuantAI*" /F >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8001.*LISTENING" 2^>nul') do taskkill /PID %%a /F >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5180.*LISTENING" 2^>nul') do taskkill /PID %%a /F >nul 2>&1
timeout /t 3 /nobreak >nul

:: 启动后端
echo [2/4] 启动后端 API (:8001)...
start "QuantAI-Backend" /MIN "%PY%" "%PROJ%\run_backend.py"
timeout /t 8 /nobreak >nul
curl -s http://localhost:8001/health >nul 2>&1
if errorlevel 1 (
    echo   [WARN] 后端未就绪 (继续启动其他服务)
) else (
    echo   [OK] 后端就绪
)

:: 启动前端
echo [3/4] 启动前端 (:5180)...
cd /d "%PROJ%\frontend"
set NODE_PATH=%NPM_PREFIX%\node_modules
start "QuantAI-Frontend" /MIN "%NPM%" run dev
cd /d "%PROJ%"
timeout /t 5 /nobreak >nul
curl -s http://localhost:5180 >nul 2>&1
if errorlevel 1 (
    echo   [WARN] 前端未就绪 (Vite可能需要更长时间)
) else (
    echo   [OK] 前端就绪
)

:: 启动 Auto Trader (10分钟循环)
echo [4/4] 启动 Auto Trader (10min cycle)...
start "QuantAI-Trader" /MIN "%PY%" "%PROJ%\auto_trader.py" --interval 600
timeout /t 3 /nobreak >nul
echo   [OK] Auto Trader 已启动

echo ============================================
echo  全部服务已启动!
echo  后端: http://localhost:8001
echo  前端: http://localhost:5180
echo  交易: 每10分钟自动执行
echo ============================================
echo  关闭此窗口不影响服务运行
echo ============================================
