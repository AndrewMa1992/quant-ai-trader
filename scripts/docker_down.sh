#!/usr/bin/env bash
# Stop one-click Docker deployment
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if docker compose version >/dev/null 2>&1; then
  docker compose --profile frontend --profile mlflow --profile pipeline down "$@"
elif command -v docker-compose >/dev/null 2>&1; then
  docker-compose --profile frontend --profile mlflow --profile pipeline down "$@"
else
  echo "docker compose not found"
  exit 1
fi

echo "Stopped Quant AI Trader containers."
