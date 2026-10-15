# ============================================
# Quant AI Trader - Backend Docker Image
# Used by the self-hosted runner CD path (legacy v1 image).
# Prefer Dockerfile.app for the current paper stack.
# ============================================
FROM python:3.11-slim AS base

WORKDIR /app

# Install system packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ============================================
# Production image
# ============================================
FROM base AS production

COPY . .

# Model placeholder directories
RUN mkdir -p backend/ai_models/models backend/data cache/torch cache/huggingface

# Environment
ENV TORCH_HOME=/app/cache/torch
ENV HF_HOME=/app/cache/huggingface
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ============================================
# Training image (GPU)
# ============================================
FROM base AS trainer

# Install PyTorch with CUDA
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cu126

COPY . .

ENV TORCH_HOME=/app/cache/torch
ENV HF_HOME=/app/cache/huggingface

CMD ["python", "-c", "import sys; sys.path.insert(0,'.'); from backend.ai_models.trainer import ModelTrainer; ModelTrainer().train_all()"]
