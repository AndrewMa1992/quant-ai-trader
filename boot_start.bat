@echo off
chcp 65001 >nul
title Quant AI Trader - Full Stack

set TORCH_HOME=G:\workbuddyspace\quant-ai-trader\cache\torch
set HF_HOME=G:\workbuddyspace\quant-ai-trader\cache\huggingface

echo Starting Quant AI Trader...
echo.

echo [1/3] Backend :8000
start "QuantTrader-Backend" /MIN python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --app-dir "G:\workbuddyspace\quant-ai-trader"

:wait_backend
timeout /t 3 /nobreak >nul
curl -s http://localhost:8000/ >nul 2>&1
if errorlevel 1 goto wait_backend

echo [2/3] Frontend :5180
cd /d G:\workbuddyspace\quant-ai-trader\frontend
start "QuantTrader-Frontend" /MIN npm run dev

echo [3/4] GitHub Runner
cd /d G:\workbuddyspace\actions-runner
start "QuantTrader-Runner" /MIN run.cmd

echo [4/4] Auto Trader (30min cycle)
cd /d G:\workbuddyspace\quant-ai-trader
start "QuantTrader-Auto" /MIN python auto_trader.py --interval 1800

echo.
echo ============================================
echo   Quant AI Trader - Running
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:5180
echo   Docs:     http://localhost:8000/docs
echo ============================================
