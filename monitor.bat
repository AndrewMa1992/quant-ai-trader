@echo off
chcp 65001 >nul
title Quant AI Trader Monitor
cd /d "G:\workbuddyspace\quant-ai-trader"

:MENU
cls
echo ============================================
echo   Quant AI Trader - 系统监控
echo ============================================
echo.
netstat -ano 2>nul | findstr ":8000 " >nul
if %errorlevel% equ 0 (echo   [BACKEND]  :8000  ^| Running) else (echo   [BACKEND]  :8000  ^| Stopped)

netstat -ano 2>nul | findstr ":5173 " >nul
if %errorlevel% equ 0 (echo   [FRONTEND] :5173  ^| Running) else (echo   [FRONTEND] :5173  ^| Stopped)
echo.
curl -s http://localhost:8000/api/models/status 2>nul
curl -s http://localhost:8000/api/trade/portfolio 2>nul
echo.
echo   1 - Start all services
echo   2 - Stop all services
echo   3 - Refresh
echo   4 - Exit
echo.
set /p choice=Choice [1-4]: 
if "%choice%"=="1" goto START
if "%choice%"=="2" goto STOP
if "%choice%"=="3" goto MENU
exit /b

:START
start "QuantTrader-Backend" /MIN python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --app-dir "%CD%"
cd frontend
start "QuantTrader-Frontend" /MIN npm run dev
cd ..
goto MENU

:STOP
taskkill /F /FI "WINDOWTITLE eq QuantTrader-Backend" 2>nul
taskkill /F /FI "WINDOWTITLE eq QuantTrader-Frontend" 2>nul
goto MENU
