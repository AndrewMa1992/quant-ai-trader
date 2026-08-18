#!/usr/bin/env bash
# ============================================================
# Quant AI Trader – One-click Docker deploy (paper / simulation)
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE=(docker compose)
if ! docker compose version >/dev/null 2>&1; then
  if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
  else
    echo "ERROR: Docker Compose is required. Install Docker Desktop / docker compose plugin."
    exit 1
  fi
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker not found. Install Docker first: https://docs.docker.com/get-docker/"
  exit 1
fi

PROFILE_FRONTEND="${PROFILE_FRONTEND:-1}"
PROFILE_MLFLOW="${PROFILE_MLFLOW:-0}"
BUILD_NO_CACHE="${BUILD_NO_CACHE:-0}"

echo "============================================"
echo "  Quant AI Trader – Docker One-Click Deploy"
echo "  Mode: PAPER / SIMULATION"
echo "  Root: $ROOT"
echo "============================================"

# 1) Env
if [[ ! -f .env ]]; then
  cp .env.docker .env
  echo "[ok] Created .env from .env.docker"
else
  echo "[ok] Using existing .env"
fi

# Ensure paper lock even if .env was customized
if ! grep -q '^QAT_EXECUTION_MODE=paper' .env 2>/dev/null; then
  echo "QAT_EXECUTION_MODE=paper" >> .env
fi
if ! grep -q '^QAT_TRADING_SIMULATION_MODE=true' .env 2>/dev/null; then
  echo "QAT_TRADING_SIMULATION_MODE=true" >> .env
fi
if ! grep -q '^QAT_USE_DOCKER=true' .env 2>/dev/null; then
  echo "QAT_USE_DOCKER=true" >> .env
fi

# 2) Directories
mkdir -p data/daily data/models cache logs mlruns
echo "[ok] data/ cache/ logs/ ready"

# 3) Profiles
PROFILES=()
if [[ "$PROFILE_FRONTEND" == "1" ]]; then
  PROFILES+=(--profile frontend)
fi
if [[ "$PROFILE_MLFLOW" == "1" ]]; then
  PROFILES+=(--profile mlflow)
fi

# 4) Build + up
echo "[..] Building images (first run may take several minutes)..."
BUILD_ARGS=(build)
if [[ "$BUILD_NO_CACHE" == "1" ]]; then
  BUILD_ARGS+=(--no-cache)
fi
"${COMPOSE[@]}" "${BUILD_ARGS[@]}"

echo "[..] Starting services..."
"${COMPOSE[@]}" "${PROFILES[@]}" up -d

# 5) Wait for gateway health
echo "[..] Waiting for API gateway health..."
API_PORT="$(grep -E '^QAT_API_PORT=' .env | cut -d= -f2 || true)"
API_PORT="${API_PORT:-8001}"
ok=0
for i in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${API_PORT}/health" >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep 3
done

echo ""
if [[ "$ok" == "1" ]]; then
  echo "============================================"
  echo "  Deploy OK (paper mode)"
  echo "  API:      http://localhost:${API_PORT}"
  echo "  Docs:     http://localhost:${API_PORT}/docs"
  echo "  Health:   http://localhost:${API_PORT}/health"
  if [[ "$PROFILE_FRONTEND" == "1" ]]; then
    FE_PORT="$(grep -E '^QAT_FRONTEND_PORT=' .env | cut -d= -f2 || true)"
    FE_PORT="${FE_PORT:-5180}"
    echo "  Frontend: http://localhost:${FE_PORT}"
  fi
  echo ""
  echo "  Status:   ${COMPOSE[*]} ps"
  echo "  Logs:     ${COMPOSE[*]} logs -f --tail=100"
  echo "  Stop:     ${COMPOSE[*]} down"
  echo "  Train:    python scripts/run_paper_train.py --quick --models gbdt"
  echo "============================================"
  exit 0
fi

echo "WARNING: gateway health not ready yet. Check logs:"
echo "  ${COMPOSE[*]} ps"
echo "  ${COMPOSE[*]} logs --tail=200"
exit 2
