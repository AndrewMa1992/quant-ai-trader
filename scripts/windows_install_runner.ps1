# Install GitHub Actions self-hosted runner on Lightsail Windows
# DeployScriptVersion: 4
# Run as Administrator once:
#   .\scripts\windows_install_runner.ps1 -Token <REGISTRATION_TOKEN>
#
# Get token:
#   GitHub repo -> Settings -> Actions -> Runners -> New self-hosted runner
#   (token expires in ~1 hour)

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Token,

    [string]$RepoUrl = "https://github.com/AndrewMa1992/quant-ai-trader",
    [string]$RunnerDir = "C:\actions-runner",
    [string]$RunnerName = "lightsail-qat",
    [string]$Labels = "self-hosted,windows,lightsail",
    [string]$Version = "2.336.0"
)

$ErrorActionPreference = "Stop"

$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
             [System.Environment]::GetEnvironmentVariable("Path", "User")

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script as Administrator."
}

Write-Host "============================================"
Write-Host "  Install Actions Runner"
Write-Host "  Dir:  $RunnerDir"
Write-Host "  Name: $RunnerName"
Write-Host "  Labels: $Labels"
Write-Host "============================================"

New-Item -ItemType Directory -Force -Path $RunnerDir | Out-Null
Set-Location $RunnerDir

$zip = "actions-runner-win-x64-$Version.zip"
$url = "https://github.com/actions/runner/releases/download/v$Version/$zip"

if (-not (Test-Path ".\config.cmd")) {
    Write-Host "[..] downloading $url"
    Invoke-WebRequest -Uri $url -OutFile $zip
    Write-Host "[..] extracting..."
    Expand-Archive -Path $zip -DestinationPath . -Force
    Remove-Item $zip -Force
} else {
    Write-Host "[ok] runner files already present"
}

if (Test-Path ".\.runner") {
    Write-Host "[warn] already configured (.runner exists)."
    Write-Host "      To reconfigure: .\config.cmd remove --token <TOKEN>"
    Write-Host "      Then re-run this script."
} else {
    Write-Host "[..] config.cmd ..."
    & .\config.cmd --unattended `
        --url $RepoUrl `
        --token $Token `
        --name $RunnerName `
        --labels $Labels `
        --work "_work" `
        --replace
    if ($LASTEXITCODE -ne 0) { throw "config.cmd failed" }
}

Write-Host "[..] install + start Windows service"
& .\svc.cmd install
if ($LASTEXITCODE -ne 0) { throw "svc install failed" }
& .\svc.cmd start
if ($LASTEXITCODE -ne 0) { throw "svc start failed" }

Write-Host ""
Write-Host "[ok] Runner installed as service"
Write-Host "  Check: GitHub -> Settings -> Actions -> Runners (Idle/Online)"
Write-Host "  Deploy: push/merge to main, or Actions -> CD Lightsail -> Run workflow"
Write-Host "  Repo app: C:\quant-ai-trader (keep separate from runner dir)"
