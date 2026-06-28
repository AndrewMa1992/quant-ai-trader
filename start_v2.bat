@echo off
echo ============================================
echo   Quant AI Trader v2.1 - Quick Start
echo ============================================
echo.
set "PY=E:\workbuddyspace\environment\pytorch-cuda\Scripts\python.exe"
set "PROJ=%~dp0"
if "%PROJ:~-1%"=="\" set "PROJ=%PROJ:~0,-1%"
set "QAT_TRAIN_DEVICE=cuda"

echo Starting API Gateway on port 8001...
start "qat-api-gateway" cmd /c "%PY% -m uvicorn api_gateway.main:app --host 0.0.0.0 --port 8001 --reload"
echo Starting Data Service on port 8011...
start "qat-data" cmd /c "%PY% -m uvicorn services.data_service.main:app --host 0.0.0.0 --port 8011"
echo Starting Factor Service on port 8012...
start "qat-factor" cmd /c "%PY% -m uvicorn services.factor_service.main:app --host 0.0.0.0 --port 8012"
echo Starting Model Train Service on port 8013...
start "qat-model-train" cmd /c "%PY% -m uvicorn services.model_train_service.main:app --host 0.0.0.0 --port 8013"
echo Starting Model Infer Service on port 8014...
start "qat-model-infer" cmd /c "%PY% -m uvicorn services.model_infer_service.main:app --host 0.0.0.0 --port 8014"
echo Starting Risk Service on port 8015...
start "qat-risk" cmd /c "%PY% -m uvicorn services.risk_service.main:app --host 0.0.0.0 --port 8015"
echo Starting Execution Service on port 8016...
start "qat-exec" cmd /c "%PY% -m uvicorn services.execution_service.main:app --host 0.0.0.0 --port 8016"
echo.
echo All services started! Press any key to stop all...
pause >nul
taskkill /f /fi "WINDOWTITLE eq qat-*" 2>nul
echo All services stopped.
