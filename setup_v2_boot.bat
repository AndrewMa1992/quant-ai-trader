@echo off
chcp 65001 >nul
:: Quant AI Trader v2 - one-click Windows boot autostart setup
:: Dual coverage: Startup folder + scheduled task (Task Scheduler)

setlocal enabledelayedexpansion

set "PROJ=%~dp0"
if "%PROJ:~-1%"=="\" set "PROJ=%PROJ:~0,-1%"

echo =============================================
echo   Quant AI Trader v2 - Boot Autostart Setup
echo   Project path: %PROJ%
echo =============================================
echo.

:: ═══════════════════════════════════════════════
:: Step 1: Verify required files exist
:: ═══════════════════════════════════════════════
echo [1/5] Verifying required files...

if not exist "%PROJ%\daemon_forever.bat" (
    echo [ERROR] daemon_forever.bat not found
    pause
    exit /b 1
)
if not exist "%PROJ%\v2_daemon_launcher.vbs" (
    echo [ERROR] v2_daemon_launcher.vbs not found; create that file first
    pause
    exit /b 1
)
echo        daemon_forever.bat    [OK]
echo        v2_daemon_launcher.vbs [OK]
echo.

:: ═══════════════════════════════════════════════
:: Step 2: Register in the Startup folder (shortcut)
:: ═══════════════════════════════════════════════
echo [2/5] Registering in the Windows Startup folder...

set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT_PATH=%STARTUP_DIR%\QuantAI-V2-Daemon.lnk"

:: Delete the old shortcut with PowerShell first (if present)
if exist "%SHORTCUT_PATH%" (
    echo       Removing old shortcut...
    del "%SHORTCUT_PATH%" 2>nul
)

:: Create a .lnk shortcut with PowerShell
powershell -NoProfile -Command ^
    "$ws = New-Object -ComObject WScript.Shell; ^
     $s = $ws.CreateShortcut('%SHORTCUT_PATH%'); ^
     $s.TargetPath = 'wscript.exe'; ^
     $s.Arguments = '%PROJ%\v2_daemon_launcher.vbs'; ^
     $s.WorkingDirectory = '%PROJ%'; ^
     $s.Description = 'Quant AI Trader v2 daemon launcher'; ^
     $s.WindowStyle = 7; ^
     $s.Save()" >nul 2>&1

if exist "%SHORTCUT_PATH%" (
    echo       Startup shortcut created [OK]
    echo       Path: %SHORTCUT_PATH%
) else (
    echo       [WARN] Shortcut creation may have failed (no admin rights?); skipping Startup
)
echo.

:: ═══════════════════════════════════════════════
:: Step 3: Delete the old scheduled task (if present)
:: ═══════════════════════════════════════════════
echo [3/5] Cleaning up old scheduled tasks...

schtasks /query /tn "QuantAI-V2-Daemon" >nul 2>&1
if not errorlevel 1 (
    schtasks /delete /tn "QuantAI-V2-Daemon" /f >nul 2>&1
    echo       Old task deleted [OK]
) else (
    echo       Nothing to clean [OK]
)
echo.

:: ═══════════════════════════════════════════════
:: Step 4: Create the scheduled task (dual coverage)
:: ═══════════════════════════════════════════════
echo [4/5] Creating scheduled task QuantAI-V2-Daemon...

:: schtasks create
:: /sc onstart  - trigger at system start
:: /delay 0001:00  - delay 60 seconds (avoid competing with system services)
:: /rl highest  - run with highest privileges
:: /f           - force overwrite

schtasks /create ^
    /tn "QuantAI-V2-Daemon" ^
    /tr "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"%PROJ%\start_daemon.ps1\"" ^
    /sc onstart ^
    /delay 0001:00 ^
    /rl highest ^
    /ru "NT AUTHORITY\SYSTEM" ^
    /f >nul 2>&1

:: Check success (may require user approval due to permissions)
schtasks /query /tn "QuantAI-V2-Daemon" >nul 2>&1
if errorlevel 1 (
    :: Fallback: run as the current user
    echo       First attempt failed; retrying with current-user privileges...
    schtasks /create ^
        /tn "QuantAI-V2-Daemon" ^
        /tr "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"%PROJ%\start_daemon.ps1\"" ^
        /sc onstart ^
        /delay 0001:00 ^
        /f >nul 2>&1
)

schtasks /query /tn "QuantAI-V2-Daemon" >nul 2>&1
if errorlevel 1 (
    echo       [WARN] schtasks is unavailable; will rely on Startup registration only
    echo       Your system may restrict scheduled-task creation
) else (
    echo       Scheduled task created [OK]
    echo       Task name: QuantAI-V2-Daemon
    echo       Trigger: 60 seconds after system start
)
echo.

:: ═══════════════════════════════════════════════
:: Step 5: Create start_daemon.ps1 (entry script for the scheduled task)
:: ═══════════════════════════════════════════════
echo [5/5] Creating PowerShell startup script...

> "%PROJ%\start_daemon.ps1" (
    echo # start_daemon.ps1 - invoked by scheduled task QuantAI-V2-Daemon
    echo # Silently start daemon_forever.bat
    echo $projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
    echo $batPath = Join-Path $projectRoot "daemon_forever.bat"
    echo if (Test-Path $batPath^) {
    echo     Start-Process -FilePath "cmd.exe" -ArgumentList "/c `"$batPath`"" -WindowStyle Hidden -WorkingDirectory $projectRoot
    echo }
)

if exist "%PROJ%\start_daemon.ps1" (
    echo       start_daemon.ps1 created [OK]
) else (
    echo       [ERROR] Unable to create start_daemon.ps1
)
echo.

:: ═══════════════════════════════════════════════
:: Completion message
:: ═══════════════════════════════════════════════
echo =============================================
echo   Setup complete!
echo =============================================
echo.
echo   Enabled boot autostart methods:
echo   1) Startup folder shortcut
echo      ^> %SHORTCUT_PATH%
echo.
schtasks /query /tn "QuantAI-V2-Daemon" >nul 2>&1
if not errorlevel 1 (
    echo   2) Windows scheduled task QuantAI-V2-Daemon
    echo      ^> Trigger: 60 seconds after system start
    echo      ^> Silent run with highest privileges
    echo   Note: the scheduled task takes effect after the next reboot
) else (
    echo   2) Scheduled task was not created (Startup only)
)
echo.
echo   After the next reboot, Quant AI Trader v2 will start automatically.
echo   To start the daemon manually, double-click:
echo     %PROJ%\daemon_forever.bat
echo.
echo   To disable boot autostart, double-click:
echo     %PROJ%\remove_v2_boot.bat
echo.
echo =============================================

:: Create the matching uninstall script
> "%PROJ%\remove_v2_boot.bat" (
    echo @echo off
    echo chcp 65001 ^>nul
    echo :: Quant AI Trader v2 - disable boot autostart
    echo set "STARTUP_DIR=%%APPDATA%%\Microsoft\Windows\Start Menu\Programs\Startup"
    echo set "SHORTCUT_PATH=%%STARTUP_DIR%%\QuantAI-V2-Daemon.lnk"
    echo echo =============================================
    echo echo   Quant AI Trader v2 - Disable Boot Autostart
    echo echo =============================================
    echo echo.
    echo if exist "%%SHORTCUT_PATH%%" (
    echo     del "%%SHORTCUT_PATH%%" 2^>nul
    echo     echo [OK] Startup shortcut deleted
    echo ^) else (
    echo     echo [OK] Startup shortcut does not exist
    echo ^)
    echo schtasks /delete /tn "QuantAI-V2-Daemon" /f ^>nul 2^>^&1
    echo if errorlevel 1 (
    echo     echo [OK] Scheduled task does not exist or was already deleted
    echo ^) else (
    echo     echo [OK] Scheduled task QuantAI-V2-Daemon deleted
    echo ^)
    echo echo.
    echo echo Boot autostart disabled. To re-enable, run setup_v2_boot.bat
    echo echo =============================================
    echo pause
)

echo Also created uninstall script: remove_v2_boot.bat
echo.

pause
