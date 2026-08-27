' v2_daemon_launcher.vbs
' Silently start daemon_forever.bat (no console flash)
' Registered into the Windows Startup folder by setup_v2_boot.bat

Dim strScriptPath
strScriptPath = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)

Dim WshShell
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c """"" & strScriptPath & "\daemon_forever.bat""""", 0, False
Set WshShell = Nothing
