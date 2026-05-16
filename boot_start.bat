@echo off
chcp 65001 >nul
title Quant AI Trader
cd /d "G:\workbuddyspace\quant-ai-trader"

:: 重定向所有缓存到项目目录（数据不流失到系统盘）
set TORCH_HOME=G:\workbuddyspace\quant-ai-trader\cache\torch
set HF_HOME=G:\workbuddyspace\quant-ai-trader\cache\huggingface
set YFINANCE_CACHE_DIR=G:\workbuddyspace\quant-ai-trader\cache\yfinance

:: 1. 启动后端
start "QuantTrader-Backend" /MIN python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --app-dir "G:\workbuddyspace\quant-ai-trader"

:: 等待后端就绪
:wait_backend
timeout /t 3 /nobreak >nul
curl -s http://localhost:8000/ >nul 2>&1
if errorlevel 1 goto wait_backend

:: 2. 启动前端
cd frontend
start "QuantTrader-Frontend" /MIN npm run dev
cd ..

echo ============================================
echo   Quant AI Trader - 已启动
echo ============================================
echo   后端API:  http://localhost:8000
echo   前端界面: http://localhost:5173
echo   数据目录: G:\workbuddyspace\quant-ai-trader\cache\
echo ============================================
