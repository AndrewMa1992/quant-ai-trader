# Quant AI Trader v2 — Service Launcher
# Double-click to start all 8 services. Processes survive after closing.
$ErrorActionPreference = "Stop"
$workdir = "E:\workbuddyspace\Claw\quant-ai-trader"
Set-Location $workdir

$env:TORCH_HOME = "$workdir\cache\torch"
$env:HF_HOME = "$workdir\cache\huggingface"
$env:HUGGINGFACE_HUB_DISABLE_SYMLINKS_WARNING = "1"
$env:PYTHONPATH = $workdir
$env:PATH = "C:\Users\hshor\.workbuddy\binaries\node\versions\22.22.2;C:\Users\hshor\.workbuddy\binaries\node\workspace\node_modules\.bin;$env:PATH"
$env:NODE_PATH = "C:\Users\hshor\.workbuddy\binaries\node\workspace\node_modules"

$py = "C:\Users\hshor\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
$node = "C:\Users\hshor\.workbuddy\binaries\node\versions\22.22.2\node.exe"

$services = @(
    @{Port=8001; Module="api_gateway.main:app"},
    @{Port=8011; Module="services.data_service.main:app"},
    @{Port=8012; Module="services.factor_service.main:app"},
    @{Port=8013; Module="services.model_train_service.main:app"},
    @{Port=8014; Module="services.model_infer_service.main:app"},
    @{Port=8015; Module="services.risk_service.main:app"},
    @{Port=8016; Module="services.execution_service.main:app"}
)

foreach ($svc in $services) {
    $proc = Start-Process $py -ArgumentList "-m","uvicorn",$svc.Module,"--host","0.0.0.0","--port",$svc.Port -PassThru -NoNewWindow
    Write-Output "Port $($svc.Port): PID $($proc.Id)"
    Start-Sleep 4
}

Write-Output "All 7 backend services launched. Starting frontend..."
Start-Sleep 2
Set-Location "$workdir\frontend"
Start-Process $node -ArgumentList "$env:NODE_PATH\.bin\vite.cmd","--port","5180","--host","0.0.0.0" -PassThru -NoNewWindow
Write-Output "Frontend launched on :5180"
Set-Location $workdir

Write-Output "`nWaiting 40s for services to come up..."
Start-Sleep 40

foreach ($svc in $services) {
    try {
        $r = Invoke-RestMethod -Uri "http://localhost:$($svc.Port)/health" -TimeoutSec 5
        Write-Output "✅ :$($svc.Port) - $($r.status)$($r.service)"
    } catch {
        Write-Output "❌ :$($svc.Port) DOWN"
    }
}
Write-Output "`nDone. Dashboard: http://localhost:5180"