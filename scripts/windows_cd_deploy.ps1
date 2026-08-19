# Smart CD deploy for Lightsail Windows (ASCII-only for PS 5.1)
# DeployScriptVersion: 5
# Usage:
#   .\scripts\windows_cd_deploy.ps1 -Branch main
#   .\scripts\windows_cd_deploy.ps1 -Branch main -Smart
#   .\scripts\windows_cd_deploy.ps1 -Branch main -FullInstall
#
# -Smart: skip stop/start when already on origin/<branch> AND gateway healthy

[CmdletBinding()]
param(
    [string]$Branch = "main",
    [string]$RepoRoot = "C:\quant-ai-trader",
    [switch]$FullInstall,
    [switch]$Smart,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
             [System.Environment]::GetEnvironmentVariable("Path", "User")

if (-not (Test-Path $RepoRoot)) {
    throw "Repo not found: $RepoRoot"
}
Set-Location $RepoRoot

New-Item -ItemType Directory -Force -Path "logs" | Out-Null
$logFile = Join-Path $RepoRoot "logs\cd-deploy.log"

function Write-Log([string]$Msg) {
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Msg
    Write-Host $line
    Add-Content -Path $logFile -Value $line -Encoding ASCII
}

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

function Test-GatewayHealthy {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8001/health" -UseBasicParsing -TimeoutSec 3
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

$GitExe = Resolve-Git
if (-not $GitExe) { throw "git not found. Install Git for Windows." }

Write-Log "==== QAT CD start branch=$Branch Smart=$Smart Force=$Force ===="

Write-Log "[..] git fetch origin"
& $GitExe fetch origin
if ($LASTEXITCODE -ne 0) { throw "git fetch failed" }

$local = (& $GitExe rev-parse HEAD 2>$null)
$remote = (& $GitExe rev-parse "origin/$Branch" 2>$null)
if (-not $remote) { throw "origin/$Branch not found. Push/merge that branch first." }

$healthy = Test-GatewayHealthy
Write-Log "[..] local=$local"
Write-Log "[..] remote=$remote"
Write-Log "[..] healthy=$healthy"

$changedFiles = @(& $GitExe diff --name-only HEAD "origin/$Branch" 2>$null)
$modelOnly = $false
if ($changedFiles -and $changedFiles.Count -gt 0) {
    $modelOnly = $true
    foreach ($f in $changedFiles) {
        if ($f -notmatch '^data/models/') { $modelOnly = $false; break }
    }
}
Write-Log ("[..] changed={0} modelOnly={1}" -f $changedFiles.Count, $modelOnly)

if ($Smart -and -not $Force) {
    if ($local -eq $remote -and $healthy) {
        Write-Log "[ok] Smart skip: already current and gateway healthy"
        exit 0
    }
}

# Fast path: only model checkpoints changed and stack is healthy -> pull + hot reload
if ($Smart -and -not $Force -and $healthy -and $modelOnly -and $local -ne $remote) {
    Write-Log "[..] model-only update: reset + infer hot-reload"
    & $GitExe checkout $Branch
    & $GitExe reset --hard "origin/$Branch"
    if ($LASTEXITCODE -ne 0) { throw "git reset failed" }
    try {
        $headers = @{ "X-API-Key" = "dev-api-key-change-in-production" }
        $r = Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:8001/api/v2/infer/predict/hot-reload" -Headers $headers -TimeoutSec 60
        Write-Log ("[ok] hot-reload: {0}" -f ($r | ConvertTo-Json -Compress))
        exit 0
    } catch {
        Write-Log "[warn] hot-reload failed, falling back to full redeploy: $($_.Exception.Message)"
    }
}

Write-Log "[..] checkout + reset --hard origin/$Branch"
& $GitExe checkout $Branch
if ($LASTEXITCODE -ne 0) { throw "git checkout $Branch failed" }
& $GitExe reset --hard "origin/$Branch"
if ($LASTEXITCODE -ne 0) { throw "git reset failed" }
& $GitExe log -1 --oneline | ForEach-Object { Write-Log $_ }

Write-Log "[..] stop old processes"
& powershell -ExecutionPolicy Bypass -File "scripts\windows_stop.ps1"

Write-Log "[..] start paper stack"
$deployArgs = @("-ExecutionPolicy", "Bypass", "-File", "scripts\windows_deploy.ps1", "-OpenFirewall")
if (-not $FullInstall) {
    $deployArgs += "-SkipInstall"
}
& powershell @deployArgs
if ($LASTEXITCODE -ne 0) { throw "windows_deploy.ps1 failed" }

Write-Log "[..] health check"
$ok = $false
for ($i = 0; $i -lt 45; $i++) {
    if (Test-GatewayHealthy) { $ok = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $ok) {
    Write-Log "[ERR] Gateway health failed after CD"
    if (Test-Path "logs\api-gateway.err.log") {
        Get-Content "logs\api-gateway.err.log" -Tail 40 | ForEach-Object { Write-Log $_ }
    }
    exit 1
}

Write-Log "[ok] CD complete - gateway healthy"
exit 0
