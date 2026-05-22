@echo off
chcp 65001 >nul
title Quant AI Trader - Full Stack

set TORCH_HOME=G:\workbuddyspace\Claw\quant-ai-trader\cache\torch
set HF_HOME=G:\workbuddyspace\Claw\quant-ai-trader\cache\huggingface

echo ============================================
echo   Quant AI Trader - Starting
echo ============================================
echo.

echo [1/3] Backend (FastAPI) :8001
cd /d G:\workbuddyspace\Claw\quant-ai-trader
start "QuantTrader-Backend" /MIN python run_backend.py

:wait_backend
timeout /t 5 /nobreak >nul
curl -s http://localhost:8001/health >nul 2>&1
if errorlevel 1 (
    echo    Waiting for backend...
    goto wait_backend
)
echo    Backend OK

echo [2/3] Frontend (Vue Dev) :5180
cd /d G:\workbuddyspace\Claw\quant-ai-trader\frontend
start "QuantTrader-Frontend" /MIN npm run dev

echo [3/3] Auto Trader (30min cycle)
cd /d G:\workbuddyspace\Claw\quant-ai-trader
start "QuantTrader-Auto" /MIN python auto_trader.py --interval 180

echo.
echo ============================================
echo   Quant AI Trader - Running
echo   Web UI:   http://localhost:5180
echo   Backend:  http://localhost:8001
echo   API Docs: http://localhost:8001/docs
echo ============================================
echo.
echo All windows minimized. Close WorkBuddy safely.
pause
