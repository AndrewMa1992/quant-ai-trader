# Install GitHub Actions self-hosted runner on Lightsail Windows
# DeployScriptVersion: 5
# Run as Administrator once:
#   .\scripts\windows_install_runner.ps1 -Token <REGISTRATION_TOKEN>
# If config already saved but service failed:
#   .\scripts\windows_install_runner.ps1 -ServiceOnly
#
# Get token:
#   GitHub repo -> Settings -> Actions -> Runners -> New self-hosted runner
#   (token expires in ~1 hour)

[CmdletBinding()]
param(
    [string]$Token = "",

    [switch]$ServiceOnly,

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

function Invoke-RunnerCmd {
    param([string]$CmdFile, [string]$Arguments)
    $full = Join-Path $RunnerDir $CmdFile
    if (-not (Test-Path $full)) {
        throw "Missing $full"
    }
    # PowerShell 5.1 often cannot invoke .cmd via & .\svc.cmd — use cmd.exe
    $p = Start-Process -FilePath "cmd.exe" `
        -ArgumentList @("/c", "`"$full`" $Arguments") `
        -WorkingDirectory $RunnerDir `
        -Wait -PassThru -NoNewWindow
    return $p.ExitCode
}

Write-Host "============================================"
Write-Host "  Install Actions Runner"
Write-Host "  Dir:  $RunnerDir"
Write-Host "  Name: $RunnerName"
Write-Host "  Labels: $Labels"
Write-Host "============================================"

New-Item -ItemType Directory -Force -Path $RunnerDir | Out-Null
Set-Location $RunnerDir

if (-not $ServiceOnly) {
    $zip = "actions-runner-win-x64-$Version.zip"
    $url = "https://github.com/actions/runner/releases/download/v$Version/$zip"

    if (-not (Test-Path (Join-Path $RunnerDir "config.cmd"))) {
        Write-Host "[..] downloading $url"
        Invoke-WebRequest -Uri $url -OutFile (Join-Path $RunnerDir $zip)
        Write-Host "[..] extracting..."
        Expand-Archive -Path (Join-Path $RunnerDir $zip) -DestinationPath $RunnerDir -Force
        Remove-Item (Join-Path $RunnerDir $zip) -Force
    } else {
        Write-Host "[ok] runner files already present"
    }

    if (Test-Path (Join-Path $RunnerDir ".runner")) {
        Write-Host "[ok] already configured (.runner exists) - skipping config"
    } else {
        if ([string]::IsNullOrWhiteSpace($Token)) {
            throw "Need -Token for first-time config (or use -ServiceOnly if already configured)."
        }
        Write-Host "[..] config.cmd ..."
        $cfgArgs = "--unattended --url $RepoUrl --token $Token --name $RunnerName --labels $Labels --work _work --replace"
        $code = Invoke-RunnerCmd "config.cmd" $cfgArgs
        if ($code -ne 0) { throw "config.cmd failed with exit $code" }
        Write-Host "[ok] Settings Saved"
    }
} else {
    Write-Host "[ok] ServiceOnly - skip download/config"
}

Write-Host "[..] install Windows service (svc.cmd install)"
$code = Invoke-RunnerCmd "svc.cmd" "install"
if ($code -ne 0) {
    Write-Host "[warn] svc install exit $code (may already be installed)"
}

Write-Host "[..] start Windows service (svc.cmd start)"
$code = Invoke-RunnerCmd "svc.cmd" "start"
if ($code -ne 0) { throw "svc.cmd start failed with exit $code" }

Write-Host ""
Write-Host "[ok] Runner installed as service"
Write-Host "  Check: GitHub -> Settings -> Actions -> Runners (Idle/Online)"
Write-Host "  Deploy: push/merge to main, or Actions -> CD Lightsail -> Run workflow"
Write-Host "  Repo app: C:\quant-ai-trader (keep separate from runner dir)"
