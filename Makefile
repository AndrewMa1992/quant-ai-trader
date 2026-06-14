# ============================================================
# Quant AI Trader v2 – Makefile
# ============================================================
SHELL := /bin/bash
.PHONY: help up down restart logs status build clean install lint test train db-init db-migrate db-seed shell

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
	awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Docker Compose ───────────────────────────────────────────
up: ## Start all services (detached)
	docker-compose up -d

down: ## Stop all services and remove containers
	docker-compose down

restart: down up ## Restart all services

logs: ## Tail logs from all services
	docker-compose logs -f --tail=100

status: ## Show running container status
	docker-compose ps

build: ## Build all Docker images
	docker-compose build --no-cache

clean: down ## Stop containers and remove volumes/images
	docker-compose down -v --rmi all

# ── Python / Dev ─────────────────────────────────────────────
install: ## Install package in editable mode with dev deps
	pip install -e ".[dev]"

lint: ## Run linters (ruff + mypy)
	ruff check .
	mypy shared/ configs/ api_gateway/

fmt: ## Format code with black + ruff
	black .
	ruff check --fix .

test: ## Run all tests
	pytest tests/ -v --cov=shared --cov=api_gateway --cov-report=term-missing

test-fast: ## Run tests excluding slow markers
	pytest tests/ -v -m "not slow"

# ── Database ─────────────────────────────────────────────────
db-init: ## Initialize database (create tables + seed data)
	python scripts/init_db.py

db-migrate: ## Generate a new Alembic migration (autogenerate)
	alembic revision --autogenerate -m "auto_migration"

db-upgrade: ## Apply pending Alembic migrations
	alembic upgrade head

db-downgrade: ## Rollback last migration
	alembic downgrade -1

db-seed: ## Re-seed market universe and factor registry
	python scripts/init_db.py --seed-only

# ── Training ─────────────────────────────────────────────────
train: ## Start model training pipeline
	curl -X POST http://localhost:8013/api/v2/models/train

# ── API Gateway ──────────────────────────────────────────────
serve: ## Run API gateway locally (dev)
	uvicorn api_gateway.main:app --host 0.0.0.0 --port 8001 --reload --log-level debug

# ── Shell ────────────────────────────────────────────────────
shell: ## Open Python REPL with app context
	python -c "from shared.database.engine import engine; from configs.settings import settings; print(f'DB: {settings.QAT_POSTGRES_URL}')" && python

# ── Frontend ─────────────────────────────────────────────────
frontend-install: ## Install frontend dependencies
	cd frontend && npm install

frontend-dev: ## Start frontend dev server
	cd frontend && npm run dev

frontend-build: ## Build frontend for production
	cd frontend && npm run build
