#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# Quant AI Trader — macOS 守护进程 (Watchdog)
# 功能：启动/监控 Backend + Frontend + AutoTrader
#       health check → 自动重启 → 熔断冷却 → git pull
# ═══════════════════════════════════════════════════════════════
set -uo pipefail

PROJ_ROOT="/Volumes/KINGSTON/workbuddyspace/Claw/quant-ai-trader"
# 优先使用 conda py312（含 torch），fallback 到项目 venv
if [ -x "/opt/miniconda3/envs/py312/bin/python3" ]; then
    DAEMON_PYTHON="/opt/miniconda3/envs/py312/bin/python3"
else
    DAEMON_PYTHON="$PROJ_ROOT/venv/bin/python"
fi
NODE_BIN="/Users/andrew/.workbuddy/binaries/node/versions/22.22.2/bin"
LOG_DIR="$PROJ_ROOT/logs"
DAEMON_LOG="$LOG_DIR/daemon.log"
PID_FILE="$LOG_DIR/daemon.pid"

# 环境变量
export TORCH_HOME="$PROJ_ROOT/cache/torch"
export HF_HOME="$PROJ_ROOT/cache/huggingface"
export SKIP_FINBERT_DOWNLOAD=1          # 无网络时快速失败，使用 VADER
export HF_HUB_DOWNLOAD_TIMEOUT=15       # HuggingFace 15秒超时
export PATH="$NODE_BIN:$PATH"

# 熔断参数
MAX_RETRIES=5
COOLDOWN_SEC=300
CHECK_INTERVAL=30

BACKEND_RETRIES=0
FRONTEND_RETRIES=0
TRADER_RETRIES=0
GIT_PULL_COUNTER=0

# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$DAEMON_LOG"
}

kill_port() {
    local port=$1
    local pid
    pid=$(lsof -ti ":$port" 2>/dev/null)
    if [ -n "$pid" ]; then
        kill -9 $pid 2>/dev/null || true
        log "  Killed stale process on :$port (PID $pid)"
    fi
}

cooldown_check() {
    local name=$1
    local retries_var=$2
    local retries=${!retries_var}
    if [ "$retries" -ge "$MAX_RETRIES" ]; then
        log "CRITICAL: $name max retries ($MAX_RETRIES) reached, cooling ${COOLDOWN_SEC}s..."
        sleep "$COOLDOWN_SEC"
        eval "$retries_var=0"
    fi
}

# ═══════════════════════════════════════════════════════════════
# 清理函数（优雅退出）
# ═══════════════════════════════════════════════════════════════

cleanup() {
    log "===== Daemon stopping, killing children ====="
    # 按进程名杀，确保清理干净
    pkill -f "run_backend.py" 2>/dev/null || true
    pkill -f "auto_trader.py" 2>/dev/null || true
    pkill -f "vite.*5180" 2>/dev/null || true
    kill_port 8001
    kill_port 5180
    sleep 2
    rm -f "$PID_FILE"
    log "===== Daemon stopped ====="
    exit 0
}

trap cleanup SIGTERM SIGINT SIGHUP

# ═══════════════════════════════════════════════════════════════
# 服务启动函数
# ═══════════════════════════════════════════════════════════════

start_backend() {
    # 已运行则跳过
    if curl -sf http://localhost:8001/health >/dev/null 2>&1; then
        BACKEND_RETRIES=0
        return 0
    fi

    cooldown_check "Backend" "BACKEND_RETRIES"

    # 杀掉残留
    kill_port 8001

    log "🔧 Starting Backend (FastAPI :8001)..."
    cd "$PROJ_ROOT"
    nohup "$DAEMON_PYTHON" run_backend.py >> "$LOG_DIR/backend.log" 2>&1 &
    local pid=$!

    # 等待健康检查通过（最多 60 秒）
    for i in $(seq 1 30); do
        sleep 2
        if curl -sf http://localhost:8001/health >/dev/null 2>&1; then
            log "✅ Backend ready (PID $pid)"
            BACKEND_RETRIES=0
            return 0
        fi
    done

    BACKEND_RETRIES=$((BACKEND_RETRIES + 1))
    log "❌ Backend failed to start (attempt $BACKEND_RETRIES/$MAX_RETRIES)"
    return 1
}

start_frontend() {
    if curl -sf http://localhost:5180 >/dev/null 2>&1; then
        FRONTEND_RETRIES=0
        return 0
    fi

    cooldown_check "Frontend" "FRONTEND_RETRIES"

    kill_port 5180

    log "🎨 Starting Frontend (Vite :5180)..."
    cd "$PROJ_ROOT/frontend" || { log "❌ Cannot cd to frontend"; return 1; }
    nohup "$NODE_BIN/npm" run dev -- --port 5180 --host 0.0.0.0 >> "$LOG_DIR/frontend.log" 2>&1 &
    local pid=$!
    cd "$PROJ_ROOT" || true

    # Vite 启动较慢，等待 30 秒
    for i in $(seq 1 15); do
        sleep 2
        if curl -sf http://localhost:5180 >/dev/null 2>&1; then
            log "✅ Frontend ready (PID $pid)"
            FRONTEND_RETRIES=0
            return 0
        fi
    done

    FRONTEND_RETRIES=$((FRONTEND_RETRIES + 1))
    log "❌ Frontend failed to start (attempt $FRONTEND_RETRIES/$MAX_RETRIES)"
    return 1
}

start_trader() {
    if pgrep -f "auto_trader.py" >/dev/null 2>&1; then
        TRADER_RETRIES=0
        return 0
    fi

    cooldown_check "AutoTrader" "TRADER_RETRIES"

    log "📊 Starting Auto Trader (10min cycle)..."
    cd "$PROJ_ROOT"
    nohup "$DAEMON_PYTHON" auto_trader.py --interval 600 >> "$LOG_DIR/trader.log" 2>&1 &
    local pid=$!
    sleep 5

    if pgrep -f "auto_trader.py" >/dev/null 2>&1; then
        log "✅ Auto Trader ready (PID $pid)"
        TRADER_RETRIES=0
        return 0
    fi

    TRADER_RETRIES=$((TRADER_RETRIES + 1))
    log "❌ Auto Trader failed to start (attempt $TRADER_RETRIES/$MAX_RETRIES)"
    return 1
}

# ═══════════════════════════════════════════════════════════════
# 主循环
# ═══════════════════════════════════════════════════════════════

main() {
    # 确保日志目录存在
    mkdir -p "$LOG_DIR"

    echo $$ > "$PID_FILE"

    log "═══════════════════════════════════════════"
    log "  Quant AI Trader — Daemon v2.1 (macOS)"
    log "═══════════════════════════════════════════"
    log "Project:  $PROJ_ROOT"
    log "Python:   $DAEMON_PYTHON"
    log "Node:     $NODE_BIN/node"
    log "PID:      $$"
    log "═══════════════════════════════════════════"

    # === 首次启动：顺序启动 ===
    start_backend
    sleep 2
    start_frontend
    sleep 2
    start_trader

    # === 持续监控循环 ===
    LAST_RESTART_TIME=$(date +%s)
    CODE_CHECK_INTERVAL=60  # 每60秒检查一次代码变更
    CODE_CHECK_COUNTER=0

    while true; do
        sleep "$CHECK_INTERVAL"

        # 健康检查 + 自动重启
        start_backend
        start_frontend
        start_trader

        # ★ 代码变更检测：有 .py 文件改动时自动重启对应服务
        CODE_CHECK_COUNTER=$((CODE_CHECK_COUNTER + 1))
        if [ "$CODE_CHECK_COUNTER" -ge 2 ]; then  # 每 60 秒检查
            CODE_CHECK_COUNTER=0
            # 检查后端代码变更 → 重启 Backend
            if [ -n "$(find "$PROJ_ROOT/backend" "$PROJ_ROOT/api_gateway" -name "*.py" -newer "$PROJ_ROOT/logs/backend.log" 2>/dev/null | head -1)" ]; then
                log "🔄 检测到后端代码变更，重启 Backend..."
                kill_port 8001
                pkill -f "run_backend.py" 2>/dev/null || true
                sleep 2
                start_backend
            fi
            # 检查交易代码变更 → 重启 Trader
            if [ -n "$(find "$PROJ_ROOT/backend/ai_models" "$PROJ_ROOT/backend/trading_engine" "$PROJ_ROOT/auto_trader.py" -name "*.py" -newer "$PROJ_ROOT/logs/trader.log" 2>/dev/null | head -1)" ]; then
                log "🔄 检测到交易代码变更，重启 Auto Trader..."
                pkill -f "auto_trader.py" 2>/dev/null || true
                sleep 2
                start_trader
            fi
        fi

        # Git pull（约每 20 次检查 = 10 分钟）
        GIT_PULL_COUNTER=$((GIT_PULL_COUNTER + 1))
        if [ "$GIT_PULL_COUNTER" -ge 20 ]; then
            (
                cd "$PROJ_ROOT" || exit
                # 静默 fetch，检查是否落后于远程
                git fetch origin 2>/dev/null
                behind=$(git rev-list HEAD..origin/dev-20260522 --count 2>/dev/null || echo "0")
                if [ "$behind" -gt 0 ] 2>/dev/null; then
                    log "Git: $behind new commit(s), pulling..."
                    git pull --rebase origin dev-20260522 >> "$DAEMON_LOG" 2>&1 || \
                        log "Git pull failed (non-blocking, continuing...)"
                fi
            ) &
            GIT_PULL_COUNTER=0
        fi
    done
}

main "$@"
