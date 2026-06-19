@echo off
:: Quant AI Trader - Quick Push (safe: uses git credential manager)
cd /d "E:\workbuddyspace\Claw\quant-ai-trader"
"C:\Program Files\Git\bin\git.exe" push -u origin dev-20260522
@echo off
if errorlevel 1 (
    echo Push failed. Ensure git credential is configured.
)
pause
