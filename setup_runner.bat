@echo off
chcp 65001 >nul
title Quant AI Trader - Self-Hosted GitHub Runner
cd /d "G:\workbuddyspace\quant-ai-trader"

echo ============================================
echo   Quant AI Trader - 自托管 Runner 安装
echo ============================================
echo.
echo  本脚本帮你安装 GitHub Actions Runner
echo  让你的电脑作为 CD Runner，用 GPU 自动训练模型
echo.
echo  前置条件：
echo  1. 代码已推送到 GitHub
echo     https://github.com/AndrewMa1992/quant-ai-trader
echo.
echo  2. 你有 GitHub 账号的访问权限
echo.
echo ============================================
echo  步骤 1：获取 Runner Token
echo ============================================
echo.
echo  在浏览器打开：
echo  https://github.com/AndrewMa1992/quant-ai-trader/settings/actions/runners/new
echo.
echo  点击 "New self-hosted runner"
echo  选 "Windows" → "X64"
echo.
echo  页面会显示一个 token，类似：
echo  AAVGxxxxxxxxxxxxxxxxxxxxxxxxx
echo.
echo  把 token 记下来，下一步要用
echo.
pause

echo.
echo ============================================
echo  步骤 2：下载并配置 Runner
echo ============================================
echo.

set /p TOKEN=请输入你的 Runner Token: 

if "%TOKEN%"=="" (
    echo [错误] Token 不能为空
    pause
    exit /b 1
)

:: 创建 Runner 目录
if not exist "C:\actions-runner" (
    mkdir C:\actions-runner
)

cd /d C:\actions-runner

:: 下载 Runner
echo 下载 GitHub Actions Runner...
curl -L -o actions-runner-win-x64-2.320.0.zip https://github.com/actions/runner/releases/download/v2.320.0/actions-runner-win-x64-2.320.0.zip
if not exist "actions-runner-win-x64-2.320.0.zip" (
    echo [错误] 下载失败，请检查网络
    pause
    exit /b 1
)

:: 解压
echo 解压中...
tar -xf actions-runner-win-x64-2.320.0.zip
del actions-runner-win-x64-2.320.0.zip

:: 配置 Runner
echo 配置 Runner...
C:\actions-runner\config.cmd --url https://github.com/AndrewMa1992/quant-ai-trader --token %TOKEN% --name "quant-trader-gpu" --labels gpu,windows --work "G:\workbuddyspace\quant-ai-trader\.github\runner-work"

echo.
echo ============================================
echo  步骤 3：安装为 Windows 服务
echo ============================================
echo.
echo 安装完成后，以管理员身份运行：
echo  C:\actions-runner\svc.cmd install
echo  C:\actions-runner\svc.cmd start
echo.
echo 然后用以下命令检查状态：
echo  C:\actions-runner\svc.cmd status
echo.
echo ============================================
echo  安装完成！
echo ============================================
echo.
echo  回到 GitHub 页面，刷新后应该能看到
echo  "quant-trader-gpu" 在线
echo.
echo  之后每次 push 代码到 main 分支：
echo  - CI: GitHub Cloud 自动检查代码
echo  - CD: 你的电脑自动拉代码 + GPU 训练
echo.
pause
