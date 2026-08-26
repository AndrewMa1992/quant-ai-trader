# Hidden Windows process launcher (ASCII, PS 5.1).
# Win32_Process.Create("cmd.exe /c ...") always shows a console - that is why
# windows_deploy.ps1 popped one cmd window per microservice.
# WScript.Shell.Run(..., 0) starts the same bat with window style Hidden.

function Start-QatHiddenBat {
    param(
        [Parameter(Mandatory = $true)][string]$BatPath,
        [string]$WorkingDirectory = "",
        [string]$CommandMatch = ""
    )
    if (-not (Test-Path -LiteralPath $BatPath)) {
        throw ("Missing bat: {0}" -f $BatPath)
    }
    if (-not $WorkingDirectory) {
        $WorkingDirectory = Split-Path -Parent $BatPath
    }

    $vbs = [System.IO.Path]::ChangeExtension($BatPath, ".vbs")
    $wdVbs = $WorkingDirectory.Replace("\", "\\")
    $runLine = 'sh.Run "cmd.exe /c ""' + $BatPath + '""", 0, False'
    $vbsLines = @(
        'Set sh = CreateObject("WScript.Shell")',
        ('sh.CurrentDirectory = "{0}"' -f $wdVbs),
        $runLine
    )
    Set-Content -LiteralPath $vbs -Value ($vbsLines -join "`r`n") -Encoding ASCII

    $wscript = Join-Path $env:SystemRoot "System32\wscript.exe"
    if (-not (Test-Path -LiteralPath $wscript)) {
        $wscript = "wscript.exe"
    }
    $cmdLine = '"{0}" //B //Nologo "{1}"' -f $wscript, $vbs
    $launcherPid = $null
    try {
        $r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
            CommandLine      = $cmdLine
            CurrentDirectory = $WorkingDirectory
        }
        if ($r.ReturnValue -eq 0) { $launcherPid = $r.ProcessId }
    } catch { }

    if (-not $launcherPid) {
        try {
            $p = Start-Process -FilePath $wscript `
                -ArgumentList @("//B", "//Nologo", $vbs) `
                -WorkingDirectory $WorkingDirectory `
                -WindowStyle Hidden `
                -PassThru
            if ($p) { $launcherPid = $p.Id }
        } catch { }
    }

    if ($CommandMatch) {
        Start-Sleep -Seconds 1
        $escaped = [regex]::Escape($CommandMatch)
        $child = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -and ($_.CommandLine -match $escaped) } |
            Select-Object -First 1
        if ($child) { return [int]$child.ProcessId }
    }
    return $launcherPid
}
