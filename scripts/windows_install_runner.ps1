# Install GitHub Actions self-hosted runner on Lightsail Windows
# DeployScriptVersion: 5
# Run as Administrator:
#   .\scripts\windows_install_runner.ps1 -Token <REGISTRATION_TOKEN>
# If already configured WITHOUT service (no svc.cmd):
#   1) Get a remove token from GitHub Runners page for this runner
#   2) .\scripts\windows_install_runner.ps1 -Token <NEW_REG_TOKEN> -RemoveToken <REMOVE_TOKEN> -ForceReconfigure
# Quick online without Windows service:
#   .\scripts\windows_install_runner.ps1 -StartInteractive
#
# IMPORTANT: zip does NOT contain svc.cmd. It is created only when
# config.cmd runs with --runasservice on Windows.

[CmdletBinding()]
param(
    [string]$Token = "",
    [string]$RemoveToken = "",
    [switch]$ForceReconfigure,
    [switch]$StartInteractive,
    [switch]$ServiceOnly,
    [string]$RepoUrl = "https://github.com/AndrewMa1992/quant-ai-trader",
    [string]$RunnerDir = "C:\actions-runner",
    [string]$RunnerName = "lightsail-qat",
    [string]$Labels = "self-hosted,windows,lightsail",
    [string]$Version = "2.336.0",
    [string]$WindowsLogonAccount = "",
    [string]$WindowsLogonPassword = ""
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

if ($StartInteractive) {
    $runCmd = Join-Path $RunnerDir "run.cmd"
    if (-not (Test-Path $runCmd)) { throw "Missing $runCmd - extract/configure runner first" }
    Write-Host "[..] starting interactive runner (keep window open)..."
    Start-Process -FilePath "cmd.exe" -ArgumentList @("/k", "`"$runCmd`"") -WorkingDirectory $RunnerDir
    Write-Host "[ok] run.cmd launched. Check GitHub Runners = Idle"
    exit 0
}

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

Write-Host "[..] files in runner dir:"
Get-ChildItem $RunnerDir -Name | Select-Object -First 20 | ForEach-Object { Write-Host "  $_" }

$runnerConfigured = Test-Path (Join-Path $RunnerDir ".runner")
$svcExists = Test-Path (Join-Path $RunnerDir "svc.cmd")

if ($ForceReconfigure -or ($runnerConfigured -and -not $svcExists)) {
    Write-Host "[warn] Runner configured but svc.cmd missing."
    Write-Host "      Windows only creates svc.cmd when config uses --runasservice."
    if ([string]::IsNullOrWhiteSpace($RemoveToken) -and -not $ForceReconfigure) {
        Write-Host ""
        Write-Host "Do ONE of the following:"
        Write-Host "  A) Quick (no reboot service):"
        Write-Host "       .\scripts\windows_install_runner.ps1 -StartInteractive"
        Write-Host "  B) Proper service: get REMOVE token from GitHub runner page, then:"
        Write-Host "       .\scripts\windows_install_runner.ps1 -Token <NEW_REG_TOKEN> -RemoveToken <REMOVE_TOKEN> -ForceReconfigure"
        exit 1
    }
    if (-not [string]::IsNullOrWhiteSpace($RemoveToken)) {
        Write-Host "[..] config.cmd remove ..."
        $code = Invoke-RunnerCmd "config.cmd" "remove --token $RemoveToken"
        Write-Host "[ok] remove exit $code"
    } elseif ($ForceReconfigure -and (Test-Path (Join-Path $RunnerDir ".runner"))) {
        Write-Host "[..] ForceReconfigure without RemoveToken: trying --replace"
    }
    $runnerConfigured = $false
}

if (-not $ServiceOnly) {
    if ($runnerConfigured -and $svcExists) {
        Write-Host "[ok] already configured with svc.cmd"
    } elseif (-not $runnerConfigured) {
        if ([string]::IsNullOrWhiteSpace($Token)) {
            throw "Need -Token for config."
        }
        Write-Host "[..] config.cmd with --runasservice ..."
        $cfgArgs = "--unattended --url $RepoUrl --token $Token --name $RunnerName --labels $Labels --work _work --replace --runasservice"
        if (-not [string]::IsNullOrWhiteSpace($WindowsLogonAccount)) {
            $cfgArgs += " --windowslogonaccount `"$WindowsLogonAccount`""
            if (-not [string]::IsNullOrWhiteSpace($WindowsLogonPassword)) {
                $cfgArgs += " --windowslogonpassword `"$WindowsLogonPassword`""
            }
        }
        $code = Invoke-RunnerCmd "config.cmd" $cfgArgs
        if ($code -ne 0) { throw "config.cmd failed with exit $code" }
        Write-Host "[ok] Settings Saved (runasservice)"
    }
}

$svcExists = Test-Path (Join-Path $RunnerDir "svc.cmd")
if ($svcExists) {
    Write-Host "[..] svc.cmd install"
    $code = Invoke-RunnerCmd "svc.cmd" "install"
    Write-Host "[ok] install exit $code"
    Write-Host "[..] svc.cmd start"
    $code = Invoke-RunnerCmd "svc.cmd" "start"
    if ($code -ne 0) { throw "svc.cmd start failed with exit $code" }
    Write-Host "[ok] Runner Windows service running"
} else {
    Write-Host "[warn] svc.cmd still missing after config."
    Write-Host "      Falling back to interactive run.cmd + startup scheduled task."
    $runCmd = Join-Path $RunnerDir "run.cmd"
    $taskName = "QAT-GitHub-Actions-Runner"
    $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$runCmd`"" -WorkingDirectory $RunnerDir
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principalTask = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principalTask -Force | Out-Null
    Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", "`"$runCmd`"") -WorkingDirectory $RunnerDir -WindowStyle Minimized
    Write-Host "[ok] Scheduled task $taskName registered; run.cmd started"
}

Write-Host ""
Write-Host "Check: GitHub -> Settings -> Actions -> Runners (Idle/Online)"
Write-Host "Deploy: merge to main, or Actions -> CD Lightsail -> Run workflow"
Write-Host "Note: service account needs git/python/npm on PATH (prefer Administrator logon)."
