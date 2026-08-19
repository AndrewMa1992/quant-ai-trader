# Stop Windows-native QAT services started by windows_deploy.ps1
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$pidDir = Join-Path $Root "cache\windows_pids"

Write-Host "Stopping Quant AI Trader (Windows)…" -ForegroundColor Cyan

if (Test-Path $pidDir) {
    Get-ChildItem $pidDir -Filter "*.pid" | ForEach-Object {
        $procId = (Get-Content $_.FullName -ErrorAction SilentlyContinue | Select-Object -First 1)
        if ($procId) {
            try {
                Stop-Process -Id ([int]$procId) -Force -ErrorAction SilentlyContinue
                Write-Host ("[ok] stopped PID {0} ({1})" -f $procId, $_.BaseName)
            } catch { }
        }
        Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
    }
}

# Fallback: kill uvicorn / vite on known ports
$ports = 8001, 8011, 8012, 8013, 8014, 8015, 8016, 5180
foreach ($port in $ports) {
    try {
        $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        foreach ($c in $conns) {
            Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
            Write-Host "[ok] freed port $port (PID $($c.OwningProcess))"
        }
    } catch { }
}

Write-Host "Done." -ForegroundColor Green
