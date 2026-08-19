# Run ON Lightsail (Sydney): download market data there, push to GitHub.
# Local GPU PC then pulls data and trains (avoids Yahoo rate-limit on home IP).
#
# Usage (Admin PowerShell on Lightsail):
#   cd C:\quant-ai-trader
#   git fetch origin; git reset --hard origin/cursor/quant-upgrade-a75f
#   .\scripts\lightsail_download_and_push.ps1
#   .\scripts\lightsail_download_and_push.ps1 -Tickers "AAPL,MSFT,GOOGL,NVDA,SPY" -ForceDownload

param(
    [string]$Tickers = "AAPL,MSFT,GOOGL,AMZN,NVDA,META,TSLA,SPY,QQQ,IWM",
    [string]$Branch = "cursor/quant-upgrade-a75f",
    [string]$RepoRoot = "C:\quant-ai-trader",
    [switch]$ForceDownload,
    [switch]$NoPush
)

$ErrorActionPreference = "Continue"
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
             [System.Environment]::GetEnvironmentVariable("Path", "User")

function Resolve-Git {
    if (Get-Command git -ErrorAction SilentlyContinue) { return (Get-Command git).Source }
    foreach ($c in @("C:\Program Files\Git\cmd\git.exe", "C:\Program Files (x86)\Git\cmd\git.exe")) {
        if (Test-Path $c) { return $c }
    }
    throw "git not found"
}

function Ensure-GitIdentity {
    param([string]$GitExe)
    $name = (& $GitExe config --get user.name 2>$null)
    $email = (& $GitExe config --get user.email 2>$null)
    if (-not $name) {
        & $GitExe config user.name "QAT Lightsail"
        Write-Host "[ok] set local git user.name = QAT Lightsail"
    }
    if (-not $email) {
        & $GitExe config user.email "qat-lightsail@users.noreply.github.com"
        Write-Host "[ok] set local git user.email = qat-lightsail@users.noreply.github.com"
    }
}

$GitExe = Resolve-Git
if (-not (Test-Path $RepoRoot)) { throw "Missing $RepoRoot" }
Set-Location $RepoRoot
Ensure-GitIdentity -GitExe $GitExe

$PythonExe = "python"
if (Test-Path "C:\Program Files\Python312\python.exe") {
    $PythonExe = "C:\Program Files\Python312\python.exe"
}

Write-Host "============================================"
Write-Host "  Lightsail (Sydney) market data download"
Write-Host "  Root: $RepoRoot"
Write-Host "============================================"

& $GitExe fetch origin 2>&1 | Out-Host
& $GitExe checkout $Branch 2>&1 | Out-Host
& $GitExe reset --hard "origin/$Branch" 2>&1 | Out-Host

$dlArgs = @("scripts\train_gpu_local.py", "--download-only", "--tickers", $Tickers)
if ($ForceDownload) { $dlArgs += "--force-download" }

Write-Host "[..] downloading via Sydney egress..."
& $PythonExe @dlArgs
if ($LASTEXITCODE -ne 0) { throw "download failed" }

Write-Host "[..] data\daily files:"
Get-ChildItem "data\daily\*.parquet" -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host ("  {0,-16} {1,10:N0} bytes" -f $_.Name, $_.Length)
}

if ($NoPush) {
    Write-Host "[ok] NoPush - data left on disk only"
    exit 0
}

$ErrorActionPreference = "Stop"
& $GitExe add -f "data/daily/*.parquet"
$status = & $GitExe status --porcelain "data/daily"
if (-not $status) {
    Write-Host "[ok] No data changes to push"
    exit 0
}

$msg = "chore: refresh market data from Lightsail $(Get-Date -Format 'yyyy-MM-dd HH:mm') [skip ci]"
& $GitExe commit -m $msg
if ($LASTEXITCODE -ne 0) { throw "git commit failed (check git user.name / user.email)" }

& $GitExe push origin $Branch
if ($LASTEXITCODE -ne 0) { throw "git push failed" }

Write-Host ""
Write-Host "[ok] Pushed data/daily. On GPU PC run:"
Write-Host "  git pull"
Write-Host "  .\scripts\train_from_lightsail_data.ps1 -Epochs 40 -SkipRl"
