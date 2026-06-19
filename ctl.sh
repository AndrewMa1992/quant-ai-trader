#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# Quant AI Trader — 服务控制脚本
# 用法: ./ctl.sh {start|stop|restart|status|logs}
# ═══════════════════════════════════════════════════════════════
PLIST_NAME="com.quant.trader"
PROJ_ROOT="/Volumes/KINGSTON/workbuddyspace/Claw/quant-ai-trader"
GUID="gui/$(id -u)"

status() {
    echo "═══════════════════════════════════════════"
    echo "  Quant AI Trader — 服务状态"
    echo "═══════════════════════════════════════════"

    # launchd 状态
    if launchctl list | grep -q "$PLIST_NAME"; then
        local pid=$(launchctl list | grep "$PLIST_NAME" | awk '{print $1}')
        echo "  launchd: ✅ 已加载 (PID $pid)"
    else
        echo "  launchd: ❌ 未加载"
    fi

    echo ""

    # Backend
    if curl -sf http://localhost:8001/health >/dev/null 2>&1; then
        echo "  Backend  :8001  ✅ 运行中"
    else
        echo "  Backend  :8001  ❌ 未运行"
    fi

    # Frontend
    if curl -sf http://localhost:5180 >/dev/null 2>&1; then
        echo "  Frontend :5180  ✅ 运行中"
    else
        echo "  Frontend :5180  ❌ 未运行"
    fi

    # Auto Trader
    if pgrep -f "auto_trader.py" >/dev/null 2>&1; then
        echo "  AutoTrader      ✅ 运行中"
    else
        echo "  AutoTrader      ❌ 未运行"
    fi

    echo ""
    echo "  Web UI:   http://localhost:5180"
    echo "  Backend:  http://localhost:8001"
    echo "  API Docs: http://localhost:8001/docs"
    echo "═══════════════════════════════════════════"
}

case "${1:-status}" in
    start)
        echo "启动服务..."
        launchctl bootstrap "$GUID" "$HOME/Library/LaunchAgents/$PLIST_NAME.plist" 2>/dev/null || \
            launchctl kickstart "$GUID/$PLIST_NAME"
        sleep 3
        status
        ;;
    stop)
        echo "停止服务..."
        launchctl bootout "$GUID/$PLIST_NAME" 2>/dev/null || echo "  服务未运行"
        ;;
    restart)
        echo "重启服务..."
        launchctl bootout "$GUID/$PLIST_NAME" 2>/dev/null
        sleep 2
        launchctl bootstrap "$GUID" "$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
        sleep 8
        status
        ;;
    status)
        status
        ;;
    logs)
        echo "守护日志 (Ctrl+C 退出):"
        tail -f "$PROJ_ROOT/logs/daemon.log"
        ;;
    *)
        echo "用法: $0 {start|stop|restart|status|logs}"
        exit 1
        ;;
esac
