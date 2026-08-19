# Run ON local GPU PC: pull market data pushed by Lightsail, then train + push models.
# DeployScriptVersion: 3
#
# Usage:
#   .\scripts\train_from_lightsail_data.ps1
#   .\scripts\train_from_lightsail_data.ps1 -Epochs 40 -SkipRl -WaitForDataMinutes 90
# Scheduled via: .\scripts\install_local_train_autostart.ps1

param(
    [string]$Tickers = "AAPL,MSFT,GOOGL,AMZN,NVDA,META,TSLA,SPY,QQQ,IWM",
    [int]$Epochs = 40,
    [string]$Branch = "cursor/quant-upgrade-a75f",
    [int]$WaitForDataMinutes = 90,
    [int]$PollSeconds = 120,
    [int]$MinParquetFiles = 5,
    [switch]$SkipRl
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

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GitArgs)
    & $GitExe @GitArgs 2>&1 | ForEach-Object {
        if ($_ -is [System.Management.Automation.ErrorRecord]) { Write-Host $_.ToString() }
        else { Write-Host $_ }
    }
    return $LASTEXITCODE
}

function Get-ParquetCount {
    return @(Get-ChildItem "data\daily\*.parquet" -ErrorAction SilentlyContinue).Count
}

$GitExe = Resolve-Git
$deadline = (Get-Date).AddMinutes([Math]::Max(0, $WaitForDataMinutes))
$attempt = 0

Write-Host "[..] waiting for Lightsail data/daily on origin/$Branch (up to $WaitForDataMinutes min)"
while ($true) {
    $attempt++
    Write-Host "[..] attempt $attempt — fetch + hard reset origin/$Branch"
    $code = Invoke-Git fetch origin
    if ($code -ne 0) { Write-Host "[warn] git fetch failed; will retry" }
    else {
        Invoke-Git checkout $Branch | Out-Null
        $code = Invoke-Git reset --hard "origin/$Branch"
        if ($code -ne 0) { throw "git reset failed" }
    }

    $n = Get-ParquetCount
    Write-Host "[ok] local parquet count: $n (need >= $MinParquetFiles)"
    if ($n -ge $MinParquetFiles) { break }

    if ((Get-Date) -ge $deadline) {
        throw "No data/daily/*.parquet after waiting $WaitForDataMinutes min. Check Lightsail QAT-Data-Download."
    }
    Write-Host "[..] sleep $PollSeconds s then retry..."
    Start-Sleep -Seconds $PollSeconds
}

$ErrorActionPreference = "Stop"
$argsList = @("-Epochs", "$Epochs", "-Tickers", $Tickers, "-Branch", $Branch, "-SkipDownload")
if ($SkipRl) { $argsList += "-SkipRl" }
& powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\train_and_sync.ps1" @argsList
if ($LASTEXITCODE -ne 0) { throw "train_and_sync failed" }

Write-Host "[ok] GPU train-from-Lightsail pipeline finished"
