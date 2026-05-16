# ============================================
# Quant AI Trader - Backend Docker Image
# 用于自托管 Runner CD 部署
# ============================================
FROM python:3.11-slim AS base

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ============================================
# Production image
# ============================================
FROM base AS production

COPY . .

# 模型占位目录
RUN mkdir -p backend/ai_models/models backend/data cache/torch cache/huggingface

# 环境变量
ENV TORCH_HOME=/app/cache/torch
ENV HF_HOME=/app/cache/huggingface
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ============================================
# Training image (带 GPU 支持)
# ============================================
FROM base AS trainer

# 安装 PyTorch 带 CUDA
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cu126

COPY . .

ENV TORCH_HOME=/app/cache/torch
ENV HF_HOME=/app/cache/huggingface

CMD ["python", "-c", "import sys; sys.path.insert(0,'.'); from backend.ai_models.trainer import ModelTrainer; ModelTrainer().train_all()"]
