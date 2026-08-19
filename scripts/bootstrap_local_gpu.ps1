# Bootstrap local GPU PC: find git, sync repo, install daily train+sync.
# DeployScriptVersion: 1
# Run as Administrator on the RTX 3060 machine:
#   Set-ExecutionPolicy -Scope Process Bypass -Force
#   irm ... OR copy this file then:
#   .\scripts\bootstrap_local_gpu.ps1
#   .\scripts\bootstrap_local_gpu.ps1 -RepoRoot C:\Quant_Trader

param(
    [string]$RepoRoot = "",
    [string]$Branch = "cursor/quant-upgrade-a75f",
    [string]$RepoUrl = "https://github.com/AndrewMa1992/quant-ai-trader.git",
    [string]$DailyAt = "02:30",
    [int]$Epochs = 40,
    [switch]$SkipRl,
    [switch]$RunNow
)

$ErrorActionPreference = "Stop"

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

if (-not (Test-Path $RepoRoot)) {
    Write-Host "[..] cloning $RepoUrl -> $RepoRoot"
    & $GitExe clone $RepoUrl $RepoRoot
}

Set-Location $RepoRoot
Write-Host "[ok] RepoRoot: $RepoRoot"

# Ensure we are on the right remote branch
& $GitExe fetch origin
& $GitExe checkout $Branch 2>$null
& $GitExe reset --hard "origin/$Branch"
if ($LASTEXITCODE -ne 0) {
    Write-Host "[warn] reset failed - trying checkout -B"
    & $GitExe checkout -B $Branch "origin/$Branch"
    & $GitExe reset --hard "origin/$Branch"
}

$installer = Join-Path $RepoRoot "scripts\install_local_train_autostart.ps1"
if (-not (Test-Path $installer)) {
    throw "Missing $installer after sync. Wrong repo?"
}

Write-Host "[..] CUDA check"
python -c "import torch; print('cuda', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'n/a')"

$argsList = @(
    "-ExecutionPolicy", "Bypass",
    "-File", $installer,
    "-RepoRoot", $RepoRoot,
    "-Branch", $Branch,
    "-DailyAt", $DailyAt,
    "-Epochs", "$Epochs"
)
if ($SkipRl) { $argsList += "-SkipRl" }
if ($RunNow) { $argsList += "-RunNow" }

& powershell @argsList
if ($LASTEXITCODE -ne 0) { throw "install_local_train_autostart failed" }

Write-Host ""
Write-Host "[ok] Bootstrap done."
Write-Host "  Daily task: QAT-Local-TrainSync at $DailyAt"
Write-Host "  Lightsail AutoCD will pull models within ~10 minutes after push."
