@echo off
chcp 65001 >nul
:: Quant AI Trader v2 - forever daemon bat script
:: Features: start all v2 services + 30s health check + git auto-sync + log rotation + self-heal after kill
:: Usage: double-click to run; place in shell:startup for boot autostart

setlocal enabledelayedexpansion

:: %~dp0 = directory of this bat script; avoids hard-coded paths
set "PROJ=%~dp0"
:: strip trailing backslash for safety
if "%PROJ:~-1%"=="\" set "PROJ=%PROJ:~0,-1%"

set "PY=C:\Users\hshor\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
set "NODE=C:\Users\hshor\.workbuddy\binaries\node\versions\22.22.2"
set "NPM=%NODE%\npm.cmd"
set "NPM_PREFIX=C:\Users\hshor\.workbuddy\binaries\node\workspace"

set TORCH_HOME=%PROJ%\cache\torch
set HF_HOME=%PROJ%\cache\huggingface
set SKIP_FINBERT_DOWNLOAD=1
set HF_HUB_DOWNLOAD_TIMEOUT=15
set PATH=%NODE%;%NPM_PREFIX%\node_modules\.bin;%PATH%
set NODE_PATH=%NPM_PREFIX%\node_modules

set QAT_TRAIN_DEVICE=cuda
set QAT_TRAIN_EPOCHS=50
set QAT_TRAIN_BATCH_SIZE=64

set CHECK_INTERVAL=30
set GIT_PULL_EVERY=20
set GIT_PUSH_EVERY=10
set MAX_RETRIES=5
set COOLDOWN_SEC=300

:: v2 ports
set API_PORT=8001
set DATA_PORT=8011
set FACTOR_PORT=8012
set TRAIN_PORT=8013
set INFER_PORT=8014
set RISK_PORT=8015
set EXEC_PORT=8016
set FRONTEND_PORT=5180

set API_RETRIES=0
set FRONTEND_RETRIES=0

title QuantAI-v2-Daemon

echo =============================================
echo   Quant AI Trader v2 - Forever Daemon
echo   Working directory: %PROJ%
echo   Health check every %CHECK_INTERVAL%s, sync code every %GIT_PULL_EVERY% cycles
echo =============================================

set /a GIT_COUNTER=0
set /a PUSH_COUNTER=0

:: ═══════════════════════════════════════════════
:: First start: launch all v2 services first (do not wait on git; avoid network stalls)
:: ═══════════════════════════════════════════════
echo [%time%] Starting all v2 services...
call :start_all
echo [%time%] Initial startup complete

:: ═══════════════════════════════════════════════
:: After start: try git pull (15s timeout; failure does not block)
:: ═══════════════════════════════════════════════
echo [%date% %time%] === Attempt: git pull latest code (15s timeout) ===
cd /d "%PROJ%"
git -c http.timeout=15 -c https.timeout=15 stash >nul 2>&1
git -c http.timeout=15 -c https.timeout=15 pull --rebase origin dev-20260522 >nul 2>&1
if errorlevel 1 (
    echo [%time%] Git pull failed/skipped (network issue, running local code)
) else (
    echo [%time%] Git pull OK - running latest code
)
cd /d "%PROJ%"

:: ═══════════════════════════════════════════════
:: Main loop - run forever
:: ═══════════════════════════════════════════════
:loop
timeout /t %CHECK_INTERVAL% /nobreak >nul

:: === git pull + auto-commit + auto-push sync ===
set /a GIT_COUNTER+=1
set /a PUSH_COUNTER+=1
if !GIT_COUNTER! geq %GIT_PULL_EVERY% (
    set /a GIT_COUNTER=0
    echo [%time%] Git: checking for updates...
    cd /d "%PROJ%"

    :: auto-commit local changes
    git -c http.timeout=15 -c https.timeout=15 add -A 2>nul
    git -c http.timeout=15 -c https.timeout=15 commit -m "auto: daemon sync %date% %time%" 2>nul

    git -c http.timeout=15 -c https.timeout=15 stash >nul 2>&1
    git -c http.timeout=15 -c https.timeout=15 fetch origin dev-20260522 2>nul

    for /f %%a in ('git rev-list HEAD..origin/dev-20260522 --count 2^>nul') do set BEHIND=%%a
    if defined BEHIND if !BEHIND! gtr 0 (
        echo [%time%] Git: !BEHIND! new commits - pulling and restarting services...
        git -c http.timeout=15 -c https.timeout=15 pull --rebase origin dev-20260522 >nul 2>&1
        if not errorlevel 1 (
            echo [%time%] Code updated. Restarting affected services...
            call :stop_all
            timeout /t 3 /nobreak >nul
            call :start_all
            echo [%time%] Services restarted with latest code
        )
    )
    cd /d "%PROJ%"
)

:: === auto-push (every %GIT_PUSH_EVERY% cycles, ~5 minutes) ===
if !PUSH_COUNTER! geq %GIT_PUSH_EVERY% (
    set /a PUSH_COUNTER=0
    echo [%time%] Git: auto-push to origin...
    cd /d "%PROJ%"
    git remote get-url origin >nul 2>&1
    if errorlevel 1 (
        echo [%time%] Git: no remote configured, skipping push
    ) else (
        git -c http.timeout=15 -c https.timeout=15 add -A 2>nul
        git -c http.timeout=15 -c https.timeout=15 commit -m "auto: daemon push %date% %time%" 2>nul
        git -c http.timeout=15 -c https.timeout=15 push origin dev-20260522 2>nul
    )
    cd /d "%PROJ%"
)

:: === API Gateway health check ===
curl -s http://localhost:%API_PORT%/health >nul 2>&1
if errorlevel 1 (
    echo [%time%] API GATEWAY DOWN - restarting...
    set /a API_RETRIES+=1
    call :check_cooldown API_GATEWAY API_RETRIES
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%API_PORT%.*LISTENING" 2^>nul') do taskkill /PID %%a /F >nul 2>&1
    start "QuantAI-API" /MIN "%PY%" -m uvicorn api_gateway.main:app --host 0.0.0.0 --port %API_PORT%
    timeout /t 10 /nobreak >nul
    curl -s http://localhost:%API_PORT%/health >nul 2>&1
    if not errorlevel 1 (
        echo [%time%] API Gateway OK
        set API_RETRIES=0
    ) else (
        echo [%time%] API Gateway still DOWN (attempt !API_RETRIES!/%MAX_RETRIES%)
    )
) else (
    set API_RETRIES=0
)

:: === Microservice health checks (probe /health one by one) ===
call :check_svc data_service %DATA_PORT%
call :check_svc factor_service %FACTOR_PORT%
call :check_svc model_train %TRAIN_PORT%
call :check_svc model_infer %INFER_PORT%
call :check_svc risk_service %RISK_PORT%
call :check_svc execution_service %EXEC_PORT%

:: === Frontend health check ===
curl -s http://localhost:%FRONTEND_PORT% >nul 2>&1
if errorlevel 1 (
    echo [%time%] FRONTEND DOWN - restarting...
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%FRONTEND_PORT%.*LISTENING" 2^>nul') do taskkill /PID %%a /F >nul 2>&1
    cd /d "%PROJ%\frontend"
    start "QuantAI-Frontend" /MIN "%NPM%" run dev
    cd /d "%PROJ%"
    timeout /t 5 /nobreak >nul
    echo [%time%] FRONTEND started
)

:: === Trading Pipeline process check ===
tasklist /FI "IMAGENAME eq python.exe" 2>nul | findstr /C:"trading_pipeline" >nul 2>&1
if errorlevel 1 (
    echo [%time%] TRADING PIPELINE DOWN - restarting...
    start "QuantAI-Pipeline" /MIN "%PY%" "%PROJ%\trading_pipeline.py" --interval 300
    timeout /t 5 /nobreak >nul
    echo [%time%] TRADING PIPELINE started
)

:: === Log rotation (every 50 cycles ~25 minutes) ===
set /a CYCLE=!RANDOM! %% 50
if !CYCLE! equ 0 (
    for %%f in ("%PROJ%\logs\api_gateway.log" "%PROJ%\logs\pipeline.log" "%PROJ%\logs\frontend.log" "%PROJ%\logs\data_service.log" "%PROJ%\logs\factor_service.log" "%PROJ%\logs\model_train.log" "%PROJ%\logs\model_infer.log" "%PROJ%\logs\risk_service.log" "%PROJ%\logs\execution_service.log") do (
        if exist %%f (
            set fsize=0
            for %%s in (%%f) do set /a fsize=%%~zs
            if !fsize! gtr 52428800 (
                move %%f %%f.bak >nul 2>&1
                echo [%time%] Log rotated: %%f (!fsize! bytes)
            )
        )
    )
)

goto :loop

:: ═══════════════════════════════════════════════
:: Subroutine: start all v2 services
:: ═══════════════════════════════════════════════
:start_all
:: === Kill leftover processes on all v2 ports first to avoid bind failures ===
echo [%time%] Killing stale processes on v2 ports...
for %%p in (%API_PORT% %DATA_PORT% %FACTOR_PORT% %TRAIN_PORT% %INFER_PORT% %RISK_PORT% %EXEC_PORT% %FRONTEND_PORT%) do (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%%p.*LISTENING" 2^>nul') do (
        taskkill /PID %%a /F >nul 2>&1
    )
)
taskkill /FI "WINDOWTITLE eq QuantAI*" /F >nul 2>&1
timeout /t 2 /nobreak >nul
echo [%time%] Stale ports cleared, launching services...

start "QuantAI-API" /MIN "%PY%" -m uvicorn api_gateway.main:app --host 0.0.0.0 --port %API_PORT%
timeout /t 3 /nobreak >nul

start "QuantAI-DataSvc" /MIN "%PY%" -m uvicorn services.data_service.main:app --host 0.0.0.0 --port %DATA_PORT%
timeout /t 2 /nobreak >nul
start "QuantAI-FactorSvc" /MIN "%PY%" -m uvicorn services.factor_service.main:app --host 0.0.0.0 --port %FACTOR_PORT%
timeout /t 2 /nobreak >nul
set QAT_TRAIN_DEVICE=cuda
start "QuantAI-TrainSvc" /MIN "%PY%" -m uvicorn services.model_train_service.main:app --host 0.0.0.0 --port %TRAIN_PORT%
timeout /t 2 /nobreak >nul
start "QuantAI-InferSvc" /MIN "%PY%" -m uvicorn services.model_infer_service.main:app --host 0.0.0.0 --port %INFER_PORT%
timeout /t 2 /nobreak >nul
start "QuantAI-RiskSvc" /MIN "%PY%" -m uvicorn services.risk_service.main:app --host 0.0.0.0 --port %RISK_PORT%
timeout /t 2 /nobreak >nul
start "QuantAI-ExecSvc" /MIN "%PY%" -m uvicorn services.execution_service.main:app --host 0.0.0.0 --port %EXEC_PORT%
timeout /t 2 /nobreak >nul

cd /d "%PROJ%\frontend"
start "QuantAI-Frontend" /MIN "%NPM%" run dev
cd /d "%PROJ%"
timeout /t 3 /nobreak >nul

start "QuantAI-Pipeline" /MIN "%PY%" "%PROJ%\trading_pipeline.py" --interval 300
goto :eof

:: ═══════════════════════════════════════════════
:: Subroutine: stop all v2 services
:: ═══════════════════════════════════════════════
:stop_all
for %%p in (%API_PORT% %DATA_PORT% %FACTOR_PORT% %TRAIN_PORT% %INFER_PORT% %RISK_PORT% %EXEC_PORT% %FRONTEND_PORT%) do (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%%p.*LISTENING" 2^>nul') do taskkill /PID %%a /F >nul 2>&1
)
taskkill /FI "WINDOWTITLE eq QuantAI*" /F >nul 2>&1
for /f "tokens=2" %%a in ('tasklist /FI "IMAGENAME eq python.exe" /FO TABLE /NH 2^>nul ^| findstr "python"') do taskkill /PID %%a /F >nul 2>&1
timeout /t 2 /nobreak >nul
goto :eof

:: ═══════════════════════════════════════════════
:: Subroutine: microservice health check
:: ═══════════════════════════════════════════════
:check_svc
curl -s http://localhost:%2/health >nul 2>&1
if errorlevel 1 (
    echo [%time%] %1 DOWN - restarting...
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%2.*LISTENING" 2^>nul') do taskkill /PID %%a /F >nul 2>&1
    start "QuantAI-Svc" /MIN "%PY%" -m uvicorn services.%1.main:app --host 0.0.0.0 --port %2
    timeout /t 5 /nobreak >nul
    echo [%time%] %1 restarted
)
goto :eof

:: ═══════════════════════════════════════════════
:: Subroutine: circuit-breaker / cooldown check
:: ═══════════════════════════════════════════════
:check_cooldown
if !%2! geq %MAX_RETRIES% (
    echo [%time%] CRITICAL: %1 max retries, cooling %COOLDOWN_SEC%s...
    timeout /t %COOLDOWN_SEC% /nobreak >nul
    set %2=0
)
goto :eof
