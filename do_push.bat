@echo off
:: Quant AI Trader - GitHub Push Script (safe: uses git credential manager)
cd /d "E:\workbuddyspace\Claw\quant-ai-trader"
set PATH=%PATH%;C:\Program Files\Git\bin;C:\Program Files\Git\cmd

:: Push (依赖系统 git credential manager 或 gh auth)
echo Pushing to GitHub...
git push origin dev-20260522 2>&1
if %errorlevel% equ 0 (
    echo SUCCESS: Push completed!
) else (
    echo FAILED with code %errorlevel%
    echo Ensure git credential is configured: git config --global credential.helper manager
)
pause
