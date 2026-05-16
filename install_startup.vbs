' Quant AI Trader - 开机启动安装脚本
' 双击运行即可

Set ws = CreateObject("WScript.Shell")
startupPath = ws.SpecialFolders("Startup")

Set shortcut = ws.CreateShortcut(startupPath & "\QuantAITrader.lnk")
shortcut.TargetPath = "cmd.exe"
shortcut.Arguments = "/c G:\workbuddyspace\quant-ai-trader\boot_start.bat"
shortcut.WorkingDirectory = "G:\workbuddyspace\quant-ai-trader"
shortcut.WindowStyle = 7
shortcut.Description = "Quant AI Trader - 量化AI交易系统"
shortcut.Save()

MsgBox "✅ 开机自启动已设置！" & vbCrLf & vbCrLf & "下次开机时系统将自动启动。" & vbCrLf & "或现在就启动：双击 boot_start.bat", vbInformation, "Quant AI Trader"
