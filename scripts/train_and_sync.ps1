# Train on local CUDA GPU, then push checkpoints so Lightsail AutoCD picks them up.
# DeployScriptVersion: 2
#
# Prerequisites:
#   - This repo cloned on the GPU PC
#   - git remote origin can push to GitHub
#   - Lightsail already has QAT-Paper-AutoCD scheduled task
#
# Usage:
#   .\scripts\train_and_sync.ps1
#   .\scripts\train_and_sync.ps1 -Epochs 30 -SkipRl
#   .\scripts\train_and_sync.ps1 -SkipTrain   # only push existing data\models

param(
    [string]$Tickers = "AAPL,MSFT,GOOGL,AMZN,NVDA,META,TSLA,SPY,QQQ,IWM",
    [int]$Epochs = 40,
    [string]$Branch = "main",
    [switch]$SkipRl,
    [switch]$SkipTrain,
    [switch]$SkipDownload,
    [switch]$ForceDownload,
    [switch]$NoPush
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

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
        & $GitExe config user.name "QAT GPU Train"
        Write-Host "[ok] set local git user.name = QAT GPU Train"
    }
    if (-not $email) {
        & $GitExe config user.email "qat-gpu@users.noreply.github.com"
        Write-Host "[ok] set local git user.email = qat-gpu@users.noreply.github.com"
    }
}

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GitArgs)
    & $GitExe @GitArgs 2>&1 | ForEach-Object {
        if ($_ -is [System.Management.Automation.ErrorRecord]) { Write-Host $_.ToString() }
        else { Write-Host $_ }
    }
    return $LASTEXITCODE
}

if ($Branch -eq "cursor/quant-upgrade-a75f") {
    Write-Host "[ok] retired branch cursor/quant-upgrade-a75f -> main (paper server tracks main)"
    $Branch = "main"
}

$GitExe = Resolve-Git
Ensure-GitIdentity -GitExe $GitExe
$PythonExe = "python"
if (Test-Path "C:\Program Files\Python312\python.exe") {
    $PythonExe = "C:\Program Files\Python312\python.exe"
}

Write-Host "============================================"
Write-Host "  QAT Train + Sync to paper server (via Git main)"
Write-Host "  Branch: $Branch"
Write-Host "============================================"

if (-not $SkipTrain) {
    $trainArgs = @("scripts\train_gpu_local.py", "--tickers", $Tickers, "--epochs", "$Epochs")
    if ($SkipRl) { $trainArgs += "--skip-rl" }
    if ($SkipDownload) { $trainArgs += "--skip-download" }
    if ($ForceDownload) { $trainArgs += "--force-download" }
    & $PythonExe @trainArgs
    if ($LASTEXITCODE -ne 0) { throw "training failed" }
} else {
    Write-Host "[ok] SkipTrain - using existing data\models"
}

$modelsDir = Join-Path $Root "data\models"
if (-not (Test-Path $modelsDir)) { throw "Missing $modelsDir" }

Write-Host "[..] model files:"
Get-ChildItem $modelsDir -File | ForEach-Object {
    Write-Host ("  {0,-32} {1,10:N0} bytes" -f $_.Name, $_.Length)
    if ($_.Length -gt 95MB) {
        Write-Host "[warn] $($_.Name) > 95MB - GitHub may reject; use SCP/S3 instead (see docs/TRAIN_SYNC.md)"
    }
}

if ($NoPush) {
    Write-Host "[ok] NoPush set - done (copy files manually or use sync_models_scp.ps1)"
    exit 0
}

# Keep the new weights aside, then publish them on top of origin/$Branch.
# A hard checkout would otherwise replace data\models with the previous commit.
Write-Host "[..] stage trained weights, then commit on origin/$Branch"
$stage = Join-Path $env:TEMP "qat-models-stage"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $stage | Out-Null
Copy-Item -Path (Join-Path $modelsDir "*") -Destination $stage -Force
if ((Invoke-Git fetch origin) -ne 0) { throw "git fetch failed" }
if ((Invoke-Git checkout -f -B $Branch "origin/$Branch") -ne 0) { throw "git checkout origin/$Branch failed" }
Copy-Item -Path (Join-Path $stage "*") -Destination $modelsDir -Force
Invoke-Git add -f -- "data/models/" | Out-Null

$status = & $GitExe status --porcelain "data/models"
if (-not $status) {
    Write-Host "[ok] No model changes to push"
    exit 0
}

$msg = "chore: update trained models $(Get-Date -Format 'yyyy-MM-dd HH:mm') [skip ci]"
$code = Invoke-Git commit -m $msg
if ($code -ne 0) { throw "git commit failed" }

Write-Host "[..] push origin/$Branch"
$code = Invoke-Git push origin $Branch
if ($code -ne 0) { throw "git push failed" }

Write-Host ""
Write-Host "[ok] Pushed data/models to origin/$Branch"
Write-Host "     The paper server QAT-Auto-Deploy pulls main within about 2 minutes"
Write-Host "     and reloads checkpoints without retraining."
