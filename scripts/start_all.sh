#!/bin/bash
# ============================================================
# Quant AI Trader — one-click start (macOS)
# Start order: Backend → AutoTrader → Watchdog
# ============================================================
set -e

PROJ_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJ_ROOT"

PYTHON="/opt/miniconda3/envs/quant/bin/python"
LOG_DIR="$PROJ_ROOT/logs"
mkdir -p "$LOG_DIR"

echo "============================================"
echo "  Quant AI Trader v2.1 — Starting All"
echo "  Project: $PROJ_ROOT"
echo "============================================"
echo ""

# 1. Kill existing processes (avoid port conflicts)
echo "[1/4] Cleaning up old processes..."
pkill -f "run_backend.py" 2>/dev/null && echo "  Old backend killed" || true
pkill -f "auto_trader.py" 2>/dev/null && echo "  Old trader killed" || true
pkill -f "watchdog.py" 2>/dev/null && echo "  Old watchdog killed" || true
sleep 2

# 2. Start Backend (FastAPI)
echo ""
echo "[2/4] Starting Backend (FastAPI :8001)..."
nohup "$PYTHON" run_backend.py > "$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
echo "  Backend PID: $BACKEND_PID"

# Wait for backend to become ready
echo "  Waiting for backend..."
for i in $(seq 1 30); do
    if curl -s http://localhost:8001/health > /dev/null 2>&1; then
        echo "  Backend OK ✓"
        break
    fi
    sleep 2
done

# 3. Start AutoTrader
echo ""
echo "[3/4] Starting AutoTrader (5min cycle, 24/7)..."
nohup "$PYTHON" auto_trader.py --interval 300 > "$LOG_DIR/trader.log" 2>&1 &
TRADER_PID=$!
echo "  AutoTrader PID: $TRADER_PID"

# 4. Start Watchdog (guards backend + trader)
echo ""
echo "[4/4] Starting Watchdog..."
nohup "$PYTHON" scripts/watchdog.py > "$LOG_DIR/watchdog_stdout.log" 2>&1 &
WATCHDOG_PID=$!
echo "  Watchdog PID: $WATCHDOG_PID"
sleep 2

echo ""
echo "============================================"
echo "  All services started!"
echo ""
echo "  Backend:   http://localhost:8001"
echo "  API Docs:  http://localhost:8001/docs"
echo "  Health:    http://localhost:8001/health"
echo ""
echo "  PIDs:"
echo "    Backend  = $BACKEND_PID"
echo "    Trader   = $TRADER_PID"
echo "    Watchdog = $WATCHDOG_PID"
echo ""
echo "  Logs: $LOG_DIR/"
echo "    backend.log  trader.log  watchdog.log"
echo ""
echo "  Stop:  ./scripts/stop_all.sh"
echo "  Check: pkill -0 $WATCHDOG_PID && echo alive"
echo "============================================"
