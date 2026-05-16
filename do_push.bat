@echo off
cd /d "G:\workbuddyspace\quant-ai-trader"
set PATH=%PATH%;C:\Program Files\Git\bin;C:\Program Files\Git\cmd
set token=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

:: Write credential file
echo https://AndrewMa1992:%token%@github.com> .git-credentials

:: Set credential helper
git config --global credential.helper "store --file G:\workbuddyspace\quant-ai-trader\.git-credentials"

:: Push
echo Pushing to GitHub...
git push origin main --force 2>&1
if %errorlevel% equ 0 (
    echo SUCCESS: Push completed!
) else (
    echo FAILED with code %errorlevel%
)
pause
