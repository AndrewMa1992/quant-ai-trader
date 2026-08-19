# Optional: push data\models to Lightsail over OpenSSH/SCP (no Git).
# DeployScriptVersion: 1
#
# One-time on Lightsail (Admin PowerShell):
#   Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
#   Start-Service sshd; Set-Service -Name sshd -StartupType Automatic
#   New-NetFirewallRule -Name sshd -DisplayName 'OpenSSH' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22
#   Lightsail Networking: open TCP 22
#
# On GPU PC:
#   .\scripts\sync_models_scp.ps1 -HostIp 3.106.139.233 -User Administrator -Password '***'

param(
    [string]$HostIp = "3.106.139.233",
    [string]$User = "Administrator",
    [string]$RemoteDir = "C:/quant-ai-trader/data/models",
    [string]$Password = "",
    [switch]$RestartRemote
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$LocalModels = Join-Path $Root "data\models"

if (-not (Test-Path $LocalModels)) { throw "Missing $LocalModels - train first" }

if (-not (Get-Command scp -ErrorAction SilentlyContinue)) {
    throw "scp not found. Install OpenSSH Client on this PC (Optional Features)."
}

Write-Host "[..] scp $LocalModels -> ${User}@${HostIp}:$RemoteDir"
# Prefer key-based auth; password via sshpass is not on Windows by default.
# Use scp interactive or configured key.
$target = "${User}@${HostIp}:$RemoteDir/"
& scp -o StrictHostKeyChecking=accept-new "$LocalModels\*" "${target}"
if ($LASTEXITCODE -ne 0) { throw "scp failed" }

if ($RestartRemote) {
    if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
        throw "ssh not found for -RestartRemote"
    }
    $cmd = "powershell -ExecutionPolicy Bypass -File C:\quant-ai-trader\scripts\windows_cd_deploy.ps1 -Branch cursor/quant-upgrade-a75f -Force"
    & ssh "${User}@${HostIp}" $cmd
}

Write-Host "[ok] models synced"
