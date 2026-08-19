# Sync repo to a remote branch (ASCII-only for PS 5.1)
# DeployScriptVersion: 4
# Usage:
#   .\scripts\windows_sync.ps1
#   .\scripts\windows_sync.ps1 -Branch main

[CmdletBinding()]
param(
    [string]$Branch = "cursor/quant-upgrade-a75f"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

# Refresh PATH (new installs of Git/Python/Node often missing until reopen)
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
             [System.Environment]::GetEnvironmentVariable("Path", "User")

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
if (-not $GitExe) {
    Write-Host "[ERR] git not found. Install Git for Windows, then reopen PowerShell."
    Write-Host "      Expected: C:\Program Files\Git\cmd\git.exe"
    exit 1
}

Write-Host "[ok] git: $GitExe"
Write-Host "[..] fetch + hard reset to origin/$Branch"

& $GitExe fetch origin
if ($LASTEXITCODE -ne 0) { throw "git fetch failed" }

& $GitExe checkout $Branch
& $GitExe reset --hard "origin/$Branch"
if ($LASTEXITCODE -ne 0) { throw "git reset failed" }

Write-Host "[ok] HEAD:"
& $GitExe log -1 --oneline

Write-Host "[ok] deploy script header:"
Get-Content (Join-Path $Root "scripts\windows_deploy.ps1") -TotalCount 3

Write-Host ""
Write-Host "Next:"
Write-Host "  Set-ExecutionPolicy -Scope Process Bypass -Force"
Write-Host "  .\scripts\windows_deploy.ps1 -OpenFirewall"
