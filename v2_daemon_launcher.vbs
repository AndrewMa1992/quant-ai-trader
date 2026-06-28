' v2_daemon_launcher.vbs
' 静默启动 daemon_forever.bat（无控制台窗口闪烁）
' 由 setup_v2_boot.bat 注册到 Windows Startup 文件夹

Dim strScriptPath
strScriptPath = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)

Dim WshShell
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c """"" & strScriptPath & "\daemon_forever.bat""""", 0, False
Set WshShell = Nothing
