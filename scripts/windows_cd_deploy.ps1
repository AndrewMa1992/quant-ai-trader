# CD deploy for Lightsail Windows (ASCII-only for PS 5.1)
# DeployScriptVersion: 4
# Called by GitHub Actions self-hosted runner OR manually:
#   .\scripts\windows_cd_deploy.ps1 -Branch main
#   .\scripts\windows_cd_deploy.ps1 -Branch main -FullInstall

[CmdletBinding()]
param(
    [string]$Branch = "main",
    [string]$RepoRoot = "C:\quant-ai-trader",
    [switch]$FullInstall
)

$ErrorActionPreference = "Stop"

$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
             [System.Environment]::GetEnvironmentVariable("Path", "User")

if (-not (Test-Path $RepoRoot)) {
    throw "Repo not found: $RepoRoot  (clone once, then install the runner)"
}
Set-Location $RepoRoot

function Resolve-Git {
    if (Get-Command git -ErrorAction SilentlyContinue) {
        return (Get-Command git).Source
    }
    foreach ($cand in @(
        "C:\Program Files\Git\cmd\git.exe",
        "C:\Program Files (x86)\Git\cmd\git.exe"
    )) {
        if (Test-Path $cand) { return $cand }
    }
    return $null
}

$GitExe = Resolve-Git
if (-not $GitExe) { throw "git not found. Install Git for Windows." }

Write-Host "============================================"
Write-Host "  QAT Lightsail CD"
Write-Host "  Root:   $RepoRoot"
Write-Host "  Branch: $Branch"
Write-Host "============================================"

Write-Host "[..] git fetch + reset --hard origin/$Branch"
& $GitExe fetch origin
if ($LASTEXITCODE -ne 0) { throw "git fetch failed" }
& $GitExe checkout $Branch
if ($LASTEXITCODE -ne 0) { throw "git checkout $Branch failed" }
& $GitExe reset --hard "origin/$Branch"
if ($LASTEXITCODE -ne 0) { throw "git reset failed" }
& $GitExe log -1 --oneline

Write-Host "[..] stop old processes"
& powershell -ExecutionPolicy Bypass -File "scripts\windows_stop.ps1"

Write-Host "[..] start paper stack"
$deployArgs = @("-ExecutionPolicy", "Bypass", "-File", "scripts\windows_deploy.ps1", "-OpenFirewall")
if (-not $FullInstall) {
    $deployArgs += "-SkipInstall"
}
& powershell @deployArgs
if ($LASTEXITCODE -ne 0) { throw "windows_deploy.ps1 failed" }

Write-Host "[..] health check"
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8001/health" -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch {
        Start-Sleep -Seconds 2
    }
}
if (-not $ok) {
    Write-Host "[ERR] Gateway health failed after CD"
    if (Test-Path "logs\api-gateway.err.log") {
        Get-Content "logs\api-gateway.err.log" -Tail 40
    }
    exit 1
}

Write-Host "[ok] CD complete - gateway healthy"
exit 0
