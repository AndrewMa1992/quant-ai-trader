@echo off
chcp 65001 >nul
:: Quant AI Trader v2 - 一键设置 Windows 开机自启
:: 双重保险：Startup 文件夹 + 计划任务（Task Scheduler）

setlocal enabledelayedexpansion

set "PROJ=%~dp0"
if "%PROJ:~-1%"=="\" set "PROJ=%PROJ:~0,-1%"

echo =============================================
echo   Quant AI Trader v2 - 开机自启设置
echo   项目路径: %PROJ%
echo =============================================
echo.

:: ═══════════════════════════════════════════════
:: 第 1 步：验证必要文件存在
:: ═══════════════════════════════════════════════
echo [1/5] 验证必要文件...

if not exist "%PROJ%\daemon_forever.bat" (
    echo [错误] 找不到 daemon_forever.bat
    pause
    exit /b 1
)
if not exist "%PROJ%\v2_daemon_launcher.vbs" (
    echo [错误] 找不到 v2_daemon_launcher.vbs，请先创建该文件
    pause
    exit /b 1
)
echo        daemon_forever.bat    [OK]
echo        v2_daemon_launcher.vbs [OK]
echo.

:: ═══════════════════════════════════════════════
:: 第 2 步：注册到 Startup 文件夹（快捷方式）
:: ═══════════════════════════════════════════════
echo [2/5] 注册到 Windows Startup 文件夹...

set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT_PATH=%STARTUP_DIR%\QuantAI-V2-Daemon.lnk"

:: 先用 PowerShell 删除旧快捷方式（如果存在）
if exist "%SHORTCUT_PATH%" (
    echo       删除旧快捷方式...
    del "%SHORTCUT_PATH%" 2>nul
)

:: 使用 PowerShell 创建 .lnk 快捷方式
powershell -NoProfile -Command ^
    "$ws = New-Object -ComObject WScript.Shell; ^
     $s = $ws.CreateShortcut('%SHORTCUT_PATH%'); ^
     $s.TargetPath = 'wscript.exe'; ^
     $s.Arguments = '%PROJ%\v2_daemon_launcher.vbs'; ^
     $s.WorkingDirectory = '%PROJ%'; ^
     $s.Description = 'Quant AI Trader v2 守护进程启动器'; ^
     $s.WindowStyle = 7; ^
     $s.Save()" >nul 2>&1

if exist "%SHORTCUT_PATH%" (
    echo       Startup 快捷方式创建成功 [OK]
    echo       路径: %SHORTCUT_PATH%
) else (
    echo       [警告] 快捷方式创建可能失败（无管理员权限？），跳过 Startup
)
echo.

:: ═══════════════════════════════════════════════
:: 第 3 步：删除旧的计划任务（如果存在）
:: ═══════════════════════════════════════════════
echo [3/5] 清理旧计划任务...

schtasks /query /tn "QuantAI-V2-Daemon" >nul 2>&1
if not errorlevel 1 (
    schtasks /delete /tn "QuantAI-V2-Daemon" /f >nul 2>&1
    echo       旧任务已删除 [OK]
) else (
    echo       无需清理 [OK]
)
echo.

:: ═══════════════════════════════════════════════
:: 第 4 步：创建计划任务（双重保险）
:: ═══════════════════════════════════════════════
echo [4/5] 创建计划任务 QuantAI-V2-Daemon...

:: schtasks 创建任务
:: /sc onstart  - 系统启动时触发
:: /delay 0001:00  - 延迟 60 秒（避免与系统服务争资源）
:: /rl highest  - 使用最高权限运行
:: /f           - 强制覆盖

schtasks /create ^
    /tn "QuantAI-V2-Daemon" ^
    /tr "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"%PROJ%\start_daemon.ps1\"" ^
    /sc onstart ^
    /delay 0001:00 ^
    /rl highest ^
    /ru "NT AUTHORITY\SYSTEM" ^
    /f >nul 2>&1

:: 检查是否成功（可能因为权限问题需要用户批准）
schtasks /query /tn "QuantAI-V2-Daemon" >nul 2>&1
if errorlevel 1 (
    :: 降级尝试：使用当前用户运行
    echo       首次尝试失败，改用当前用户权限重试...
    schtasks /create ^
        /tn "QuantAI-V2-Daemon" ^
        /tr "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"%PROJ%\start_daemon.ps1\"" ^
        /sc onstart ^
        /delay 0001:00 ^
        /f >nul 2>&1
)

schtasks /query /tn "QuantAI-V2-Daemon" >nul 2>&1
if errorlevel 1 (
    echo       [警告] schtasks 命令不可用，将仅依赖 Startup 注册
    echo       您的系统可能限制计划任务创建
) else (
    echo       计划任务创建成功 [OK]
    echo       任务名: QuantAI-V2-Daemon
    echo       触发器: 系统启动后延迟 60 秒
)
echo.

:: ═══════════════════════════════════════════════
:: 第 5 步：创建 start_daemon.ps1（计划任务调用的入口脚本）
:: ═══════════════════════════════════════════════
echo [5/5] 创建 PowerShell 启动脚本...

> "%PROJ%\start_daemon.ps1" (
    echo # start_daemon.ps1 - 由计划任务 QuantAI-V2-Daemon 调用
    echo # 静默启动 daemon_forever.bat
    echo $projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
    echo $batPath = Join-Path $projectRoot "daemon_forever.bat"
    echo if (Test-Path $batPath^) {
    echo     Start-Process -FilePath "cmd.exe" -ArgumentList "/c `"$batPath`"" -WindowStyle Hidden -WorkingDirectory $projectRoot
    echo }
)

if exist "%PROJ%\start_daemon.ps1" (
    echo       start_daemon.ps1 创建成功 [OK]
) else (
    echo       [错误] 无法创建 start_daemon.ps1
)
echo.

:: ═══════════════════════════════════════════════
:: 完成提示
:: ═══════════════════════════════════════════════
echo =============================================
echo   设置完成！
echo =============================================
echo.
echo   已启用的开机自启方式:
echo   1) Startup 文件夹快捷方式
echo      ^> %SHORTCUT_PATH%
echo.
schtasks /query /tn "QuantAI-V2-Daemon" >nul 2>&1
if not errorlevel 1 (
    echo   2) Windows 计划任务 QuantAI-V2-Daemon
    echo      ^> 触发器: 系统启动后延迟 60 秒
    echo      ^> 以最高权限静默运行
    echo   注意: 计划任务将在下一次系统重启后生效
) else (
    echo   2) 计划任务未成功（仅依赖 Startup）
)
echo.
echo   下次重启计算机后，Quant AI Trader v2 将自动启动。
echo   如需手动启动守护进程，双击运行:
echo     %PROJ%\daemon_forever.bat
echo.
echo   如需取消开机自启，双击运行:
echo     %PROJ%\remove_v2_boot.bat
echo.
echo =============================================

:: 创建对应的卸载脚本
> "%PROJ%\remove_v2_boot.bat" (
    echo @echo off
    echo chcp 65001 ^>nul
    echo :: Quant AI Trader v2 - 取消开机自启
    echo set "STARTUP_DIR=%%APPDATA%%\Microsoft\Windows\Start Menu\Programs\Startup"
    echo set "SHORTCUT_PATH=%%STARTUP_DIR%%\QuantAI-V2-Daemon.lnk"
    echo echo =============================================
    echo echo   Quant AI Trader v2 - 取消开机自启
    echo echo =============================================
    echo echo.
    echo if exist "%%SHORTCUT_PATH%%" (
    echo     del "%%SHORTCUT_PATH%%" 2^>nul
    echo     echo [OK] 已删除 Startup 快捷方式
    echo ^) else (
    echo     echo [OK] Startup 快捷方式不存在
    echo ^)
    echo schtasks /delete /tn "QuantAI-V2-Daemon" /f ^>nul 2^>^&1
    echo if errorlevel 1 (
    echo     echo [OK] 计划任务不存在或已删除
    echo ^) else (
    echo     echo [OK] 已删除计划任务 QuantAI-V2-Daemon
    echo ^)
    echo echo.
    echo echo 开机自启已取消。如需重新启用，请运行 setup_v2_boot.bat
    echo echo =============================================
    echo pause
)

echo 已同时创建卸载脚本: remove_v2_boot.bat
echo.

pause
