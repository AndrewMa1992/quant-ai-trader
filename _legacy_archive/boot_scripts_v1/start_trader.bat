@echo off
REM ========================================
REM  Auto Trader 守护进程启动脚本
REM  自动重启意外退出的交易系统
REM ========================================

setlocal

set PROJECT_DIR=%~dp0
set LOG_DIR=%PROJECT_DIR%logs

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo [%date% %time%] Auto Trader Daemon Started >> "%LOG_DIR%\daemon.log"

:loop
echo [%date% %time%] Starting auto_trader.py... >> "%LOG_DIR%\daemon.log"

python "%PROJECT_DIR%auto_trader.py" --interval 300

set EXIT_CODE=%ERRORLEVEL%
echo [%date% %time%] auto_trader.py exited with code %EXIT_CODE% >> "%LOG_DIR%\daemon.log"

REM 等待5秒后重启
echo [%date% %time%] Restarting in 5 seconds... >> "%LOG_DIR%\daemon.log"
timeout /t 5 /nobreak > nul

goto loop
