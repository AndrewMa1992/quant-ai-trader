# Train QAT models on a Windows PC with NVIDIA GPU (e.g. RTX 3060)
# Run in the repo root on the GPU machine (NOT on Lightsail CPU):
#   Set-ExecutionPolicy -Scope Process Bypass -Force
#   .\scripts\train_gpu_local.ps1

param(
    [string]$Tickers = "AAPL,MSFT,GOOGL,AMZN,NVDA,META,TSLA,SPY,QQQ,IWM",
    [int]$Epochs = 40,
    [switch]$SkipRl,
    [switch]$SkipDownload
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
             [System.Environment]::GetEnvironmentVariable("Path", "User")

$PythonExe = "python"
if (Test-Path "C:\Program Files\Python312\python.exe") {
    $PythonExe = "C:\Program Files\Python312\python.exe"
}

Write-Host "============================================"
Write-Host "  QAT Local GPU Train"
Write-Host "  Root: $Root"
Write-Host "============================================"

& $PythonExe -c "import torch; print('cuda', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'n/a')"

$argsList = @("scripts\train_gpu_local.py", "--tickers", $Tickers, "--epochs", "$Epochs")
if ($SkipRl) { $argsList += "--skip-rl" }
if ($SkipDownload) { $argsList += "--skip-download" }

& $PythonExe @argsList
if ($LASTEXITCODE -ne 0) { throw "train_gpu_local.py failed" }

Write-Host ""
Write-Host "Copy models to Lightsail:"
Write-Host "  data\models\*.joblib / *.pt / *.zip  ->  C:\quant-ai-trader\data\models\"
Write-Host "Then restart: .\scripts\windows_deploy.ps1 -SkipInstall"
