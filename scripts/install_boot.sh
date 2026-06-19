#!/bin/bash
# ============================================================
# Quant AI Trader — macOS 开机自启安装脚本
# 
# 使用方法（在 WorkBuddy 外部的终端中执行）：
#   chmod +x scripts/install_boot.sh
#   ./scripts/install_boot.sh
#
# 这会做两件事：
#   1. 安装 launchd plist → 开机自动启动 watchdog
#   2. 安装 crontab → 每日健康检查 + 日志清理
# ============================================================
set -e

PROJ_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "============================================"
echo "  Quant AI Trader — Boot Installer"
echo "  Project: $PROJ_ROOT"
echo "============================================"
echo ""

# 1. Install launchd plist
PLIST_SRC="$PROJ_ROOT/scripts/com.quant.trader.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.quant.trader.plist"

if [ -f "$PLIST_SRC" ]; then
    mkdir -p "$HOME/Library/LaunchAgents"
    cp "$PLIST_SRC" "$PLIST_DST"
    echo "[1/3] LaunchAgent plist installed: $PLIST_DST"
    
    # Unload old → load new
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    if launchctl load "$PLIST_DST" 2>/dev/null; then
        echo "       LaunchAgent loaded ✓ (auto-start on boot)"
    else
        echo "       LaunchAgent load failed, but file is in place."
        echo "       Reboot or run: launchctl load $PLIST_DST"
    fi
else
    echo "[1/3] SKIP: plist not found at $PLIST_SRC"
fi

# 2. Install crontab
CRON_FILE="$PROJ_ROOT/scripts/quant_trader.cron"

cat > "$CRON_FILE" << 'CRONEOF'
# Quant AI Trader — Crontab (installed by install_boot.sh)
# @reboot: Start 60s after boot (wait for network/storage mount)
@reboot sleep 60 && /bin/bash VOLUME_PLACEHOLDER/scripts/start_all.sh >> VOLUME_PLACEHOLDER/logs/cron_reboot.log 2>&1
# @daily: Health check at 04:00
0 4 * * * curl -sf http://localhost:8001/health > /dev/null 2>&1 || /bin/bash VOLUME_PLACEHOLDER/scripts/start_all.sh >> VOLUME_PLACEHOLDER/logs/cron_daily.log 2>&1
# @daily: Rotate logs older than 7 days
0 3 * * * find VOLUME_PLACEHOLDER/logs/ -name "*.log" -mtime +7 -delete
CRONEOF

# Replace placeholder with actual path
sed -i '' "s|VOLUME_PLACEHOLDER|$PROJ_ROOT|g" "$CRON_FILE"

# Install crontab
if crontab -l 2>/dev/null | grep -q "Quant AI Trader"; then
    echo "[2/3] Crontab already exists, skipping..."
else
    (crontab -l 2>/dev/null; cat "$CRON_FILE") | crontab - 2>/dev/null && \
        echo "[2/3] Crontab installed ✓" || \
        echo "[2/3] Crontab FAILED (try manually: crontab $CRON_FILE)"
fi

# 3. Verify
echo ""
echo "[3/3] Verification:"
echo "  Crontab entries:"
crontab -l 2>/dev/null | grep -i "quant\|trader" | sed 's/^/    /' || echo "    (none)"

echo ""
echo "============================================"
echo "  Boot auto-start configured!"
echo ""
echo "  开机自启:  macOS LaunchAgent (watchdog)"
echo "  备用方案:  crontab @reboot (start_all.sh)"
echo "  每日检查:  04:00 health check"
echo ""
echo "  手动操作:"
echo "    启动:  ./scripts/start_all.sh"
echo "    停止:  ./scripts/stop_all.sh"
echo "    状态:  pgrep -fl 'watchdog\|auto_trader\|run_backend'"
echo "    日志:  tail -f logs/watchdog.log"
echo "============================================"
