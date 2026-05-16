@echo off
chcp 65001 >nul
title Quant AI Trader Monitor
cd /d "%~dp0"

:MENU
cls
echo ============================================
echo   Quant AI Trader - 系统监控
echo ============================================
echo.

:: 检查端口
netstat -ano 2>nul | findstr ":8000 " >nul
if %errorlevel% equ 0 (
    echo   [BACKEND]  :8000  ✅ 运行中
) else (
    echo   [BACKEND]  :8000  ❌ 未启动
)

netstat -ano 2>nul | findstr ":5173 " >nul
if %errorlevel% equ 0 (
    echo   [FRONTEND] :5173  ✅ 运行中
) else (
    echo   [FRONTEND] :5173  ❌ 未启动
)

:: 检查模型
curl -s http://localhost:8000/api/models/status 2>nul | python -c "import sys,json; d=json.load(sys.stdin); print(f'   [MODEL]    Transformer: {\"ready\" if d.get(\"transformer_ready\") else \"not ready\"}, RL: {\"ready\" if d.get(\"rl_ready\") else \"not ready\"}')" 2>nul

:: 检查持仓
curl -s http://localhost:8000/api/trade/portfolio 2>nul | python -c "import sys,json; d=json.load(sys.stdin); m=d['metrics']; print(f'   [PORTFOLIO] Value: ${m[\"total_value\"]:.0f}, Cash: ${m[\"cash\"]:.0f}, Positions: {m[\"num_positions\"]}')" 2>nul

echo.
echo   1 - 启动所有服务
echo   2 - 停止所有服务
echo   3 - 刷新状态
echo   4 - 退出
echo.
set /p choice=选择 [1-4]: 

if "%choice%"=="1" goto START_ALL
if "%choice%"=="2" goto STOP_ALL
if "%choice%"=="3" goto MENU
if "%choice%"=="4" exit /b

:START_ALL
echo.
echo 启动服务...
start "QuantTrader-Backend" /MIN python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --app-dir "%CD%"
cd frontend
start "QuantTrader-Frontend" /MIN npm run dev
cd ..
echo 服务已启动，按任意键返回...
pause >nul
goto MENU

:STOP_ALL
echo.
echo 停止所有服务...
taskkill /F /FI "WINDOWTITLE eq QuantTrader-Backend" 2>nul
taskkill /F /FI "WINDOWTITLE eq QuantTrader-Frontend" 2>nul
taskkill /F /IM python.exe /FI "WINDOWTITLE eq uvicorn" 2>nul
taskkill /F /IM node.exe /FI "WINDOWTITLE eq QuantTrader-Frontend" 2>nul
echo 已停止，按任意键返回...
pause >nul
goto MENU
