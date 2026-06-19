#!/bin/bash
# ============================================================
# Quant AI Trader — 停止所有服务 (macOS)
# ============================================================
echo "Stopping Quant AI Trader..."

# 停止 watchdog 优先（避免它重启其他进程）
pkill -f "scripts/watchdog.py" 2>/dev/null && echo "  Watchdog stopped" || echo "  Watchdog not running"

# 停止自动交易引擎
pkill -f "auto_trader.py" 2>/dev/null && echo "  AutoTrader stopped" || echo "  AutoTrader not running"

# 停止后端
pkill -f "run_backend.py" 2>/dev/null && echo "  Backend stopped" || echo "  Backend not running"

sleep 1
echo "All services stopped."
