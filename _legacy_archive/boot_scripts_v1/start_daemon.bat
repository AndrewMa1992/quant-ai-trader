@echo off
chcp 65001 >nul
title QuantAI Daemon

:: Quant AI Trader - Daemon Launcher
:: Place this shortcut in Startup folder for auto-start

cd /d E:\workbuddyspace\Claw\quant-ai-trader

:: Run PowerShell daemon
powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "E:\workbuddyspace\Claw\quant-ai-trader\daemon_win.ps1"
