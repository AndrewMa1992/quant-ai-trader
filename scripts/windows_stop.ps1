# Stop Windows-native QAT services started by windows_deploy.ps1
# DeployScriptVersion: 7
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$pidDir = Join-Path $Root "cache\windows_pids"

Write-Host "Stopping Quant AI Trader (Windows)..."

if (Test-Path $pidDir) {
    Get-ChildItem $pidDir -Filter "*.pid" | ForEach-Object {
        $procId = (Get-Content $_.FullName -ErrorAction SilentlyContinue | Select-Object -First 1)
        if ($procId) {
            try {
                Stop-Process -Id ([int]$procId) -Force -ErrorAction SilentlyContinue
                Write-Host ("[ok] stopped PID {0} ({1})" -f $procId, $_.BaseName)
            } catch { }
        }
        Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
    }
}

# Hidden wscript launchers may not own the python child - kill by command line too
$patterns = @(
    "uvicorn api_gateway.main:app",
    "uvicorn services.data_service.main:app",
    "uvicorn services.factor_service.main:app",
    "uvicorn services.model_train_service.main:app",
    "uvicorn services.model_infer_service.main:app",
    "uvicorn services.risk_service.main:app",
    "uvicorn services.execution_service.main:app",
    "windows_frontend_server.py",
    "run_pipeline.py",
    "trading_pipeline.py"
)
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object {
    $cl = $_.CommandLine
    if (-not $cl) { return }
    foreach ($pat in $patterns) {
        if ($cl -like ("*{0}*" -f $pat)) {
            try {
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
                Write-Host ("[ok] stopped PID {0} ({1})" -f $_.ProcessId, $pat)
            } catch { }
            break
        }
    }
}

$ports = 8001, 8011, 8012, 8013, 8014, 8015, 8016, 5180
foreach ($port in $ports) {
    try {
        $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        foreach ($c in $conns) {
            Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
            Write-Host "[ok] freed port $port (PID $($c.OwningProcess))"
        }
    } catch { }
}

Write-Host "Done."
