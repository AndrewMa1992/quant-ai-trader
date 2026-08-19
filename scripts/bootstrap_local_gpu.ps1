# Bootstrap local GPU PC: find git, sync repo, install daily train+sync.
# DeployScriptVersion: 3
# Run as Administrator on the RTX 3060 machine:
#   Set-ExecutionPolicy -Scope Process Bypass -Force
#   .\scripts\bootstrap_local_gpu.ps1 -RepoRoot C:\Quant_Trader -DailyAt "03:00" -Epochs 40 -SkipRl -RunNow

param(
    [string]$RepoRoot = "",
    [string]$Branch = "cursor/quant-upgrade-a75f",
    [string]$RepoUrl = "https://github.com/AndrewMa1992/quant-ai-trader.git",
    [string]$DailyAt = "03:00",
    [int]$Epochs = 40,
    [int]$WaitForDataMinutes = 90,
    [switch]$SkipRl,
    [switch]$RunNow
)

# Do not Stop on git stderr noise like "Already on 'branch'"
$ErrorActionPreference = "Continue"

# Refresh PATH (Git/Python often missing until reopen)
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
             [System.Environment]::GetEnvironmentVariable("Path", "User")

function Resolve-Git {
    if (Get-Command git -ErrorAction SilentlyContinue) {
        return (Get-Command git).Source
    }
    foreach ($c in @(
        "C:\Program Files\Git\cmd\git.exe",
        "C:\Program Files (x86)\Git\cmd\git.exe"
    )) {
        if (Test-Path $c) { return $c }
    }
    return $null
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
if (-not $GitExe) {
    Write-Host "[ERR] Git not found. Install Git for Windows:"
    Write-Host "  https://git-scm.com/download/win"
    Write-Host "Or winget: winget install --id Git.Git -e"
    Write-Host "Then reopen PowerShell and re-run this script."
    exit 1
}
Write-Host "[ok] git: $GitExe"

if (-not $RepoRoot) {
    if ($PSScriptRoot) {
        $RepoRoot = Split-Path -Parent $PSScriptRoot
    } else {
        $RepoRoot = "C:\Quant_Trader"
    }
}

if (-not (Test-Path (Join-Path $RepoRoot ".git"))) {
    if (Test-Path $RepoRoot) {
        Write-Host "[warn] $RepoRoot exists but is not a git repo"
    }
    Write-Host "[..] cloning $RepoUrl -> $RepoRoot"
    $parent = Split-Path -Parent $RepoRoot
    $name = Split-Path -Leaf $RepoRoot
    if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    Set-Location $parent
    $code = Invoke-Git clone $RepoUrl $name
    if ($code -ne 0 -and -not (Test-Path (Join-Path $RepoRoot ".git"))) {
        throw "git clone failed"
    }
}

Set-Location $RepoRoot
Write-Host "[ok] RepoRoot: $RepoRoot"

Write-Host "[..] sync branch $Branch"
Invoke-Git fetch origin | Out-Null
Invoke-Git checkout $Branch | Out-Null
$code = Invoke-Git reset --hard "origin/$Branch"
if ($code -ne 0) {
    Write-Host "[warn] reset failed - trying checkout -B"
    Invoke-Git checkout -B $Branch "origin/$Branch" | Out-Null
    $code = Invoke-Git reset --hard "origin/$Branch"
    if ($code -ne 0) { throw "git reset failed" }
}
Invoke-Git log -1 --oneline | Out-Null

$installer = Join-Path $RepoRoot "scripts\install_local_train_autostart.ps1"
if (-not (Test-Path $installer)) {
    throw "Missing $installer after sync. Wrong repo?"
}

Write-Host "[..] CUDA check"
try {
    python -c "import torch; print('cuda', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'n/a')"
} catch {
    Write-Host "[warn] python/torch check failed: $($_.Exception.Message)"
}

$ErrorActionPreference = "Stop"
$argsList = @(
    "-ExecutionPolicy", "Bypass",
    "-File", $installer,
    "-RepoRoot", $RepoRoot,
    "-Branch", $Branch,
    "-DailyAt", $DailyAt,
    "-Epochs", "$Epochs",
    "-WaitForDataMinutes", "$WaitForDataMinutes"
)
if ($SkipRl) { $argsList += "-SkipRl" }
if ($RunNow) { $argsList += "-RunNow" }

& powershell @argsList
if ($LASTEXITCODE -ne 0) { throw "install_local_train_autostart failed" }

Write-Host ""
Write-Host "[ok] Bootstrap done."
Write-Host "  Daily task: QAT-Local-TrainSync at $DailyAt (from Lightsail data)"
Write-Host "  Lightsail should run: install_lightsail_data_autostart.ps1 (~01:00)"
Write-Host "  Lightsail AutoCD will pull models within ~10 minutes after push."
