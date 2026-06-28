@echo off
chcp 65001 >nul
:: Quant AI Trader v2 - Cancel Boot Auto-start
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT_PATH=%STARTUP_DIR%\QuantAI-V2-Daemon.lnk"
echo =============================================
echo   Quant AI Trader v2 - Cancel Boot Auto-start
echo =============================================
echo.
if exist "%SHORTCUT_PATH%" (
    del "%SHORTCUT_PATH%" 2>nul
    echo [OK] Startup shortcut deleted
) else (
    echo [OK] Startup shortcut doesn't exist
)
schtasks /delete /tn "QuantAI-V2-Daemon" /f >nul 2>&1
if errorlevel 1 (
    echo [OK] Scheduled task doesn't exist or already deleted
) else (
    echo [OK] Deleted scheduled task QuantAI-V2-Daemon
)
echo.
echo Boot auto-start cancelled. To re-enable, run setup_v2_boot.bat
echo =============================================
pause
