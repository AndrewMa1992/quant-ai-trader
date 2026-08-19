# Run ON local GPU PC: pull market data pushed by Lightsail, then train + push models.
# DeployScriptVersion: 2
#
# Usage:
#   .\scripts\train_from_lightsail_data.ps1
#   .\scripts\train_from_lightsail_data.ps1 -Epochs 40 -SkipRl

param(
    [string]$Tickers = "AAPL,MSFT,GOOGL,AMZN,NVDA,META,TSLA,SPY,QQQ,IWM",
    [int]$Epochs = 40,
    [string]$Branch = "cursor/quant-upgrade-a75f",
    [switch]$SkipRl
)

# Do not Stop on git stderr noise like "Already on 'branch'"
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
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $GitExe @GitArgs 2>&1 | ForEach-Object {
        if ($_ -is [System.Management.Automation.ErrorRecord]) {
            Write-Host $_.ToString()
        } else {
            Write-Host $_
        }
    }
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prev
    return $code
}

$GitExe = Resolve-Git
Write-Host "[..] pull latest (includes data/daily from Lightsail if pushed)"
$code = Invoke-Git fetch origin
if ($code -ne 0) { throw "git fetch failed" }
$code = Invoke-Git checkout $Branch
# exit 0 even when "Already on branch"
$code = Invoke-Git reset --hard "origin/$Branch"
if ($code -ne 0) { throw "git reset failed" }

$n = (Get-ChildItem "data\daily\*.parquet" -ErrorAction SilentlyContinue | Measure-Object).Count
Write-Host "[ok] local parquet count: $n"
if ($n -lt 1) {
    throw "No data/daily/*.parquet after pull. First run lightsail_download_and_push.ps1 on the Sydney instance."
}

$ErrorActionPreference = "Stop"
$argsList = @("-Epochs", "$Epochs", "-Tickers", $Tickers, "-Branch", $Branch, "-SkipDownload")
if ($SkipRl) { $argsList += "-SkipRl" }
& powershell -ExecutionPolicy Bypass -File "scripts\train_and_sync.ps1" @argsList
if ($LASTEXITCODE -ne 0) { throw "train_and_sync failed" }
