#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# Quant AI Trader — 一键安装守护进程 (macOS launchd)
# 功能：复制 plist → 加载 launchd → 验证服务
# ═══════════════════════════════════════════════════════════════
set -uo pipefail

PLIST_NAME="com.quant.trader"
PROJ_ROOT="/Volumes/KINGSTON/workbuddyspace/Claw/quant-ai-trader"
PLIST_SRC="$PROJ_ROOT/$PLIST_NAME.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"

echo "═══════════════════════════════════════════"
echo "  Quant AI Trader — 守护进程安装"
echo "═══════════════════════════════════════════"
echo ""

# Step 1: 确保 LaunchAgents 目录存在
mkdir -p "$HOME/Library/LaunchAgents"

# Step 2: 复制 plist
echo "[1/4] 复制 launchd 配置..."
cp "$PLIST_SRC" "$PLIST_DST"
echo "  ✅ $PLIST_DST"

# Step 3: 卸载已有实例（如果存在）
echo "[2/4] 停止旧实例（如果有）..."
launchctl bootout "gui/$(id -u)/$PLIST_NAME" 2>/dev/null || echo "  (无旧实例运行)"

# Step 4: 加载 launchd 服务（最多重试 3 次）
echo "[3/4] 加载 launchd 服务..."
LOADED=false
for attempt in 1 2 3; do
    sleep 1
    if launchctl bootstrap "gui/$(id -u)" "$PLIST_DST" 2>/dev/null; then
        LOADED=true
        echo "  ✅ 服务已加载"
        break
    fi
    echo "  重试 $attempt/3..."
done
if [ "$LOADED" = false ]; then
    echo "  ⚠️  自动加载失败，请手动执行:"
    echo "     launchctl bootstrap gui/\$(id -u) $PLIST_DST"
fi

# Step 5: 等待并验证
echo "[4/4] 验证服务状态..."
sleep 8

echo ""
echo "═══════════════════════════════════════════"
echo "  服务状态报告"
echo "═══════════════════════════════════════════"

# Backend
if curl -sf http://localhost:8001/health >/dev/null 2>&1; then
    echo "  Backend  :8001  ✅ 运行中"
else
    echo "  Backend  :8001  ⏳ 启动中（请稍等...）"
fi

# Frontend
if curl -sf http://localhost:5180 >/dev/null 2>&1; then
    echo "  Frontend :5180  ✅ 运行中"
else
    echo "  Frontend :5180  ⏳ 启动中（请稍等...）"
fi

# Auto Trader
if pgrep -f "auto_trader.py" >/dev/null 2>&1; then
    echo "  AutoTrader      ✅ 运行中"
else
    echo "  AutoTrader      ⏳ 启动中（请稍等...）"
fi

echo ""
echo "═══════════════════════════════════════════"
echo "  Web UI:   http://localhost:5180"
echo "  Backend:  http://localhost:8001"
echo "  API Docs: http://localhost:8001/docs"
echo "═══════════════════════════════════════════"
echo ""
echo "📋 常用命令："
echo "  launchctl list | grep quant      # 查看状态"
echo "  tail -f logs/daemon.log          # 查看守护日志"
echo "  launchctl kickstart gui/\$(id -u)/$PLIST_NAME  # 强制重启守护"
echo ""
echo "🚀 守护进程安装完成！开机将自动启动。"
