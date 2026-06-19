@echo off
chcp 65001 >nul
:: Quant AI Trader - GitHub 推送脚本
:: 运行前先在浏览器打开:
:: https://github.com/AndrewMa1992/quant-ai-trader
:: 点 Code -> HTTPS -> 复制仓库地址

cd /d "G:\workbuddyspace\quant-ai-trader"

echo ============================================
echo  Quant AI Trader - 推送到 GitHub
echo ============================================
echo.
echo 操作步骤:
echo.
echo  1. 在 GitHub 上创建空仓库:
echo     https://github.com/new
echo     - Repository name: quant-ai-trader
echo     - 不要勾任何选项
echo     - 点 "Create repository"
echo.
echo  2. 回到这里按任意键...
pause >nul

echo.
echo 正在推送到 GitHub...
echo.

"C:\Program Files\Git\bin\git.exe" remote add origin https://github.com/AndrewMa1992/quant-ai-trader.git 2>nul
"C:\Program Files\Git\bin\git.exe" push -u origin main --force

echo.
echo ============================================
echo  推送完成！
echo  查看: https://github.com/AndrewMa1992/quant-ai-trader
echo ============================================
pause
