@echo off
chcp 65001 >nul
title QuantAI-Guard
set "PROJ=G:\workbuddyspace\Claw\quant-ai-trader"
set "PY=%PROJ%\venv\Scripts\python.exe"
set "LOG=%PROJ%\logs\guard.log"
set "MAX_RETRIES=5"
set "RETRY_COUNT=0"

cd /d "%PROJ%"

echo %date% %time% GUARD STARTED >> %LOG%

:loop
:: === BACKEND ===
curl -s http://localhost:8001/health >nul 2>&1
if errorlevel 1 (
    echo %time% BACKEND DOWN - starting (retry %RETRY_COUNT%/%MAX_RETRIES%) >> %LOG%
    taskkill /FI "WINDOWTITLE eq QuantAI-Backend*" /F >nul 2>&1
    start "QuantAI-Backend" /MIN "%PY%" run_backend.py
    timeout /t 8 /nobreak >nul
    curl -s http://localhost:8001/health >nul 2>&1
    if errorlevel 1 (
        set /a RETRY_COUNT+=1
        echo %time% BACKEND failed to start (attempt %RETRY_COUNT%) >> %LOG%
    ) else (
        set RETRY_COUNT=0
        echo %time% BACKEND started OK >> %LOG%
    )
) else (
    set RETRY_COUNT=0
)

:: === FRONTEND ===
curl -s http://localhost:5180 >nul 2>&1
if errorlevel 1 (
    echo %time% FRONTEND DOWN - starting >> %LOG%
    taskkill /FI "WINDOWTITLE eq QuantAI-Frontend*" /F >nul 2>&1
    cd /d "%PROJ%\frontend"
    start "QuantAI-Frontend" /MIN cmd /c npm run dev
    cd /d "%PROJ%"
    timeout /t 5 /nobreak >nul
    curl -s http://localhost:5180 >nul 2>&1
    if errorlevel 1 (
        echo %time% FRONTEND still DOWN - checking npm deps >> %LOG%
        cd /d "%PROJ%\frontend"
        start "QuantAI-Frontend" /MIN cmd /c "npm install && npm run dev"
        cd /d "%PROJ%"
    )
)

:: === AUTO TRADER ===
tasklist /FI "IMAGENAME eq python.exe" 2>nul | findstr /C:"auto_trader" >nul 2>&1
if errorlevel 1 (
    echo %time% TRADER DOWN - starting >> %LOG%
    start "QuantAI-Trader" /MIN "%PY%" auto_trader.py --interval 600
    timeout /t 3 /nobreak >nul
)

:: === MAX RETRIES CIRCUIT BREAKER ===
if %RETRY_COUNT% geq %MAX_RETRIES% (
    echo %time% BACKEND max retries reached - cooling down 5min >> %LOG%
    timeout /t 300 /nobreak >nul
    set RETRY_COUNT=0
)

:: === GIT PULL (every 20 checks ~10 min) ===
set /a N=%RANDOM% %% 20
if %N% equ 0 (
    echo %time% GIT pull >> %LOG%
    git pull origin main >> %LOG% 2>&1
)

timeout /t 30 /nobreak >nul
goto :loop
