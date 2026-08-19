# Install Redis (or Memurai) on Windows for QAT quote/signal cache.
# DeployScriptVersion: 1
# Admin PowerShell:
#   .\scripts\windows_install_redis.ps1
#   .\scripts\windows_install_redis.ps1 -Start

param(
    [switch]$Start
)

$ErrorActionPreference = "Continue"
Write-Host "============================================"
Write-Host "  QAT Redis install (Windows)"
Write-Host "============================================"

$redisCmd = Get-Command redis-server -ErrorAction SilentlyContinue
if ($redisCmd) {
    Write-Host "[ok] redis-server already on PATH: $($redisCmd.Source)"
} else {
    Write-Host "[..] trying winget Memurai Developer (Redis-compatible)..."
    winget install --id Memurai.MemuraiDeveloper -e --accept-package-agreements --accept-source-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                 [System.Environment]::GetEnvironmentVariable("Path", "User")
}

# Fallback: chocolatey
if (-not (Get-Command redis-server -ErrorAction SilentlyContinue) -and (Get-Command choco -ErrorAction SilentlyContinue)) {
    Write-Host "[..] trying choco install redis-64..."
    choco install redis-64 -y
}

if (-not (Get-Command redis-server -ErrorAction SilentlyContinue) -and -not (Get-Service Memurai* -ErrorAction SilentlyContinue)) {
    Write-Host "[warn] Redis/Memurai not found."
    Write-Host "  Install Memurai: https://www.memurai.com/"
    Write-Host "  Or run Redis in WSL: wsl sudo service redis-server start"
    Write-Host "  Pipeline will degrade to in-memory cache if Redis is down."
    exit 0
}

if ($Start) {
    $svc = Get-Service -Name "Memurai*" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($svc) {
        if ($svc.Status -ne "Running") { Start-Service $svc.Name }
        Write-Host "[ok] Memurai service: $($svc.Status)"
    } else {
        Start-Process redis-server -WindowStyle Minimized
        Write-Host "[ok] started redis-server"
    }
}

Write-Host ""
Write-Host "Set in .env:"
Write-Host "  QAT_REDIS_URL=redis://127.0.0.1:6379/0"
Write-Host "  QAT_REDIS_HOST=127.0.0.1"
Write-Host "  QAT_REDIS_PORT=6379"
Write-Host "  QAT_REDIS_PASSWORD="
