# Pull GitHub main and redeploy the paper stack when it changes.
# DeployScriptVersion: 2
# ASCII-only for Windows PowerShell 5.1.
#
#   .\scripts\windows_auto_deploy.ps1 -InstallTask
#   .\scripts\windows_auto_deploy.ps1 -Once
#
# The scheduled task polls every 2 minutes. Ignored files stay put:
# .env, certs\, logs\, cache\, and frontend\dist\ are not removed.

[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\quant-ai-trader",
    [string]$Branch = "main",
    [string]$RemoteUrl = "https://github.com/AndrewMa1992/quant-ai-trader.git",
    [switch]$InstallTask,
    [switch]$Once
)

$ErrorActionPreference = "Continue"

$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
             [System.Environment]::GetEnvironmentVariable("Path", "User")

function Resolve-Git {
    foreach ($cand in @(
        "C:\Program Files\Git\cmd\git.exe",
        "C:\Program Files\Git\bin\git.exe",
        "C:\Program Files (x86)\Git\cmd\git.exe"
    )) {
        if (Test-Path $cand) { return $cand }
    }
    $cmd = Get-Command git -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Write-Log([string]$Msg) {
    $dir = Join-Path $RepoRoot "logs"
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Msg
    Add-Content -Path (Join-Path $dir "auto-deploy.log") -Value $line -Encoding ASCII
    Write-Host $line
}

function Invoke-Git {
    param([string]$GitExe, [string[]]$GitArgs)
    # Capture git's text so a success message is not treated as a failed exit code.
    $output = & $GitExe -c "safe.directory=$RepoRoot" -C $RepoRoot @GitArgs 2>&1 | Out-String
    $code = $LASTEXITCODE
    if ($output -and $output.Trim()) {
        foreach ($line in ($output.Trim() -split "\r?\n")) {
            if ($line) { Write-Log ("git " + $line) }
        }
    }
    return $code
}

function Ensure-Repo {
    param([string]$GitExe)
    if (-not (Test-Path $RepoRoot)) {
        throw "Repo not found: $RepoRoot"
    }
    $gitDir = Join-Path $RepoRoot ".git"
    if (-not (Test-Path $gitDir)) {
        Write-Log "git init"
        if ((Invoke-Git $GitExe @("init")) -ne 0) { throw "git init failed" }
    }
    $remotes = & $GitExe -c "safe.directory=$RepoRoot" -C $RepoRoot remote 2>$null
    if ($remotes -notcontains "origin") {
        Write-Log "git remote add origin"
        if ((Invoke-Git $GitExe @("remote", "add", "origin", $RemoteUrl)) -ne 0) {
            throw "git remote add failed"
        }
    }
}

if ($InstallTask) {
    $scriptPath = Join-Path $RepoRoot "scripts\windows_auto_deploy.ps1"
    if (-not (Test-Path $scriptPath)) {
        throw "Missing $scriptPath"
    }
    $arg = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -Once' -f $scriptPath
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory $RepoRoot
    $start = (Get-Date).AddMinutes(1)
    $repeat = New-ScheduledTaskTrigger -Once -At $start `
        -RepetitionInterval (New-TimeSpan -Minutes 2) `
        -RepetitionDuration ([TimeSpan]::FromDays(3650))
    $boot = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    Register-ScheduledTask -TaskName "QAT-Auto-Deploy" -Action $action `
        -Trigger @($boot, $repeat) -Principal $principal -Settings $settings `
        -Description "QAT: deploy origin/main within 2 minutes of a GitHub update" -Force | Out-Null
    Write-Log "Registered QAT-Auto-Deploy (every 2 minutes, branch=$Branch)"
    exit 0
}

if (-not $Once) {
    $Once = $true
}

$GitExe = Resolve-Git
if (-not $GitExe) {
    Write-Log "[ERR] git not found"
    exit 1
}

$lockDir = Join-Path $RepoRoot "cache"
if (-not (Test-Path $lockDir)) {
    New-Item -ItemType Directory -Force -Path $lockDir | Out-Null
}
$lock = Join-Path $lockDir "auto-deploy.lock"
if (Test-Path $lock) {
    $age = (Get-Date) - (Get-Item $lock).LastWriteTime
    if ($age.TotalMinutes -lt 40) {
        Write-Log "[skip] deploy already running"
        exit 0
    }
    Write-Log "[warn] stale lock removed"
    Remove-Item $lock -Force -ErrorAction SilentlyContinue
}

$exitCode = 0
try {
    Set-Content -Path $lock -Value (Get-Date -Format "o") -Encoding ASCII
    Ensure-Repo $GitExe

    Write-Log "[..] git fetch origin $Branch"
    if ((Invoke-Git $GitExe @("fetch", "origin", $Branch)) -ne 0) {
        Write-Log "[ERR] git fetch failed"
        $exitCode = 1
    } else {
        $remote = (& $GitExe -c "safe.directory=$RepoRoot" -C $RepoRoot rev-parse "origin/$Branch" 2>$null)
        if (-not $remote) {
            Write-Log "[ERR] origin/$Branch not found"
            $exitCode = 1
        } else {
            $remote = "$remote".Trim()
            $shaFile = Join-Path $lockDir "deployed_sha.txt"
            $deployed = ""
            if (Test-Path $shaFile) {
                $deployed = (Get-Content $shaFile -Raw).Trim()
            }
            if ($deployed -eq $remote) {
                Write-Log "[ok] already current $remote"
            } else {
                Write-Log "[..] update $deployed -> $remote"
                $modelOnly = $false
                if ($deployed) {
                    $names = & $GitExe -c "safe.directory=$RepoRoot" -C $RepoRoot diff --name-only $deployed $remote 2>$null
                    $list = @($names | Where-Object { $_ -and "$_".Trim() })
                    if ($list.Count -gt 0) {
                        $modelOnly = $true
                        foreach ($f in $list) {
                            if ("$f".Trim() -notmatch '^data/models/') { $modelOnly = $false; break }
                        }
                    }
                }
                if ((Invoke-Git $GitExe @("checkout", "-f", "-B", $Branch, "origin/$Branch")) -ne 0) {
                    Write-Log "[ERR] git checkout failed"
                    $exitCode = 1
                } elseif ($modelOnly) {
                    Write-Log "[..] model-only update: keep the stack up and reload checkpoints"
                    $reloaded = $false
                    try {
                        $headers = @{ "X-API-Key" = "dev-api-key-change-in-production" }
                        $r = Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:8001/api/v2/infer/predict/hot-reload" -Headers $headers -TimeoutSec 60
                        Write-Log ("[ok] infer hot-reload {0}" -f ($r | ConvertTo-Json -Compress))
                        $reloaded = $true
                    } catch {
                        Write-Log ("[warn] infer hot-reload failed, full redeploy: {0}" -f $_.Exception.Message)
                    }
                    if ($reloaded) {
                        Set-Content -Path $shaFile -Value $remote -Encoding ASCII
                        Write-Log "[ok] deployed $remote (models only; paper loop reloads data/models)"
                    } else {
                        $deploy = Join-Path $RepoRoot "scripts\windows_cd_deploy.ps1"
                        Write-Log "[..] windows_cd_deploy -Branch $Branch"
                        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $deploy -Branch $Branch
                        $exitCode = $LASTEXITCODE
                        if ($exitCode -ne 0) {
                            Write-Log "[ERR] deploy exit $exitCode - will retry"
                        } else {
                            Set-Content -Path $shaFile -Value $remote -Encoding ASCII
                            Write-Log "[ok] deployed $remote"
                        }
                    }
                } else {
                    $deploy = Join-Path $RepoRoot "scripts\windows_cd_deploy.ps1"
                    Write-Log "[..] windows_cd_deploy -Branch $Branch"
                    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $deploy -Branch $Branch
                    $exitCode = $LASTEXITCODE
                    if ($exitCode -ne 0) {
                        Write-Log "[ERR] deploy exit $exitCode - will retry"
                    } else {
                        Set-Content -Path $shaFile -Value $remote -Encoding ASCII
                        Write-Log "[ok] deployed $remote"
                    }
                }
            }
        }
    }
} finally {
    if (Test-Path $lock) {
        Remove-Item $lock -Force -ErrorAction SilentlyContinue
    }
}
exit $exitCode
