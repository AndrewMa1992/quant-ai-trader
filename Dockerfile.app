# Quant AI Trader v2 – unified application image (paper / one-click deploy)
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive \
    PYTHONPATH=/app \
    QAT_USE_DOCKER=true \
    QAT_EXECUTION_MODE=paper \
    QAT_TRADING_SIMULATION_MODE=true \
    QAT_TRAIN_DEVICE=cpu

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libgomp1 \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install lean runtime deps first (better layer cache)
COPY requirements.docker.txt ./
RUN pip install --no-cache-dir -r requirements.docker.txt

# Application source
COPY pyproject.toml README.md ./
COPY shared/ ./shared/
COPY configs/ ./configs/
COPY api_gateway/ ./api_gateway/
COPY services/ ./services/
COPY backend/ ./backend/
COPY scripts/ ./scripts/
COPY trading_pipeline.py ./

RUN mkdir -p /app/data/daily /app/data/models /app/cache /app/logs /app/mlruns \
    && touch shared/__init__.py services/__init__.py

EXPOSE 8001 8011 8012 8013 8014 8015 8016

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 \
    CMD curl -f http://localhost:8001/health || exit 1

CMD ["uvicorn", "api_gateway.main:app", "--host", "0.0.0.0", "--port", "8001", "--log-level", "info"]
