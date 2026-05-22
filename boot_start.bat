@echo off
chcp 65001 >nul
title Quant AI Trader - Full Stack

set TORCH_HOME=G:\workbuddyspace\Claw\quant-ai-trader\cache\torch
set HF_HOME=G:\workbuddyspace\Claw\quant-ai-trader\cache\huggingface

echo Starting Quant AI Trader...
echo.

echo [1/3] Backend (includes Frontend SPA) :8000
cd /d G:\workbuddyspace\Claw\quant-ai-trader
start "QuantTrader-Backend" /MIN python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

:wait_backend
timeout /t 3 /nobreak >nul
curl -s http://localhost:8000/health >nul 2>&1
if errorlevel 1 goto wait_backend

echo [2/3] GitHub Runner
cd /d G:\workbuddyspace\actions-runner
rem Fix exFAT junction issue: ensure bin & externals directories exist
if not exist "bin\Runner.Listener.exe" (
    for /f "tokens=*" %%i in ('dir /b /ad /on bin.* 2^>nul ^| sort /r') do (
        if not exist "bin\" (
            echo Copying %%i -^> bin
            xcopy "%%i" "bin\" /E /I /Q /Y
        )
    )
)
if not exist "externals\node20" (
    if not exist "externals\node24" (
        for /f "tokens=*" %%i in ('dir /b /ad /on externals.* 2^>nul ^| sort /r') do (
            if not exist "externals\" (
                echo Copying %%i -^> externals
                xcopy "%%i" "externals\" /E /I /Q /Y
            )
        )
    )
)
start "QuantTrader-Runner" /MIN run.cmd

echo [3/3] Auto Trader (30min cycle)
cd /d G:\workbuddyspace\Claw\quant-ai-trader
start "QuantTrader-Auto" /MIN python auto_trader.py --interval 1800

echo.
echo ============================================
echo   Quant AI Trader - Running
echo   Web UI:   http://localhost:8000
echo   API Docs: http://localhost:8000/docs
echo ============================================
