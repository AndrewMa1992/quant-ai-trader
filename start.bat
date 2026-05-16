@echo off
chcp 65001 >nul
title Quant AI Trader
cd /d "%~dp0"

:: 重定向所有缓存到项目目录
set TORCH_HOME=%CD%\cache\torch
set HF_HOME=%CD%\cache\huggingface
set YFINANCE_CACHE_DIR=%CD%\cache\yfinance

echo ============================================
echo   Quant AI Trader - 量化AI交易系统
echo   GPU: NVIDIA GeForce RTX 3060
echo ============================================
echo.

:: 1. 启动后端
echo [1/3] 启动后端API服务 (port 8000)...
start "QuantTrader-Backend" /MIN python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --app-dir "%CD%"

:: 等待后端就绪
echo   等待后端启动...
:wait_backend
timeout /t 3 /nobreak >nul
curl -s http://localhost:8000/ >nul 2>&1
if errorlevel 1 goto wait_backend
echo   ✅ 后端就绪: http://localhost:8000

:: 2. 启动前端
echo [2/3] 启动前端界面 (port 5173)...
cd frontend
if not exist "node_modules" (
    echo   安装前端依赖...
    call npm install
)
start "QuantTrader-Frontend" /MIN npm run dev
cd ..

echo [3/3] 检查模型状态...
curl -s http://localhost:8000/api/models/status 2>&1

echo.
echo ============================================
echo   系统已启动！所有数据保存在项目内
echo ============================================
echo   后端API:    http://localhost:8000
echo   API文档:    http://localhost:8000/docs
echo   前端界面:   http://localhost:5180
echo   数据缓存:   %CD%\cache\
echo   日志文件:   %CD%\logs\
echo   数据库:     %CD%\backend\data\
echo   模型文件:   %CD%\backend\ai_models\models\
echo ============================================
echo.
start http://localhost:5180
pause
