# Docker One-Click Deploy (Paper / Simulation)

## Prerequisites
- Docker Engine + Compose plugin (Docker Desktop OK)
- ~4GB free disk for first image build

## One command

```bash
chmod +x scripts/docker_deploy.sh scripts/docker_down.sh
./scripts/docker_deploy.sh
```

This will:
1. Create `.env` from `.env.docker` if missing (paper mode locked)
2. Create `data/`, `cache/`, `logs/`
3. Build the unified app image
4. Start Postgres, Redis, API gateway, and all microservices
5. Start frontend (nginx) by default
6. Wait until `http://localhost:8001/health` responds

## URLs

| Service | URL |
|---------|-----|
| API Gateway | http://localhost:8001 |
| API Docs | http://localhost:8001/docs |
| Frontend | http://localhost:5180 |
| Data | http://localhost:8011/health |
| Risk | http://localhost:8015/health |

## Common commands

```bash
# Status / logs
docker compose ps
docker compose logs -f --tail=100

# Include MLflow
PROFILE_MLFLOW=1 ./scripts/docker_deploy.sh

# Skip frontend
PROFILE_FRONTEND=0 ./scripts/docker_deploy.sh

# Paper train (on host, uses data/ volume)
python scripts/run_paper_train.py --quick --models gbdt

# Run one pipeline cycle inside compose
docker compose --profile pipeline run --rm trading-pipeline

# Stop everything
./scripts/docker_down.sh
# or: make down
```

## Paper mode

Defaults force simulation:
- `QAT_EXECUTION_MODE=paper`
- `QAT_TRADING_SIMULATION_MODE=true`
- `QAT_USE_DOCKER=true`

Do **not** enable live Tiger trading from this compose stack until credentials and risk checks are verified.

## Troubleshooting

- Gateway unhealthy: `docker compose logs api-gateway data-service --tail=200`
- Redis auth fail: ensure `.env` `QAT_REDIS_PASSWORD` matches compose
- Rebuild clean: `BUILD_NO_CACHE=1 ./scripts/docker_deploy.sh`
