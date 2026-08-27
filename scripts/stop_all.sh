#!/bin/bash
# ============================================================
# Quant AI Trader — stop all services (macOS)
# ============================================================
echo "Stopping Quant AI Trader..."

# Stop watchdog first (so it does not restart other processes)
pkill -f "scripts/watchdog.py" 2>/dev/null && echo "  Watchdog stopped" || echo "  Watchdog not running"

# Stop the auto-trading engine
pkill -f "auto_trader.py" 2>/dev/null && echo "  AutoTrader stopped" || echo "  AutoTrader not running"

# Stop the backend
pkill -f "run_backend.py" 2>/dev/null && echo "  Backend stopped" || echo "  Backend not running"

sleep 1
echo "All services stopped."
