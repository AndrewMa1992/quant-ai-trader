"""验证所有模块导入"""
import sys
sys.path.insert(0, '.')

print("=" * 50)
print("Quant AI Trader - 模块导入验证")
print("=" * 50)

# Core
import torch; print(f"PyTorch {torch.__version__}")
import numpy as np; print(f"NumPy {np.__version__}")
import pandas as pd; print(f"Pandas {pd.__version__}")

# Config
from backend.config import data_config, model_config, trading_config
print(f"Config: {len(data_config.TICKERS)} tickers, ${trading_config.INITIAL_CAPITAL} capital")

# Data Engine
from backend.data_engine import MarketDataEngine, DataPipeline, HistoricalStore, RealtimeEngine
print("Data Engine OK")

# AI Models
from backend.ai_models import TransformerPredictor, SignalEnsemble, SentimentAnalyzer
print("AI Models OK")

# Trading Engine
from backend.trading_engine import PortfolioManager, RiskManager, PaperExecutor, Backtester
print("Trading Engine OK")

# API
from backend.api import routes_data, routes_trade, routes_analysis, routes_models
print("API Routes OK")

# Full pipeline test
from backend.trading_engine.strategy import TradingStrategy
print("Strategy Module OK")

from backend.ai_models.trainer import ModelTrainer
print("Trainer Module OK")

print("=" * 50)
print("ALL IMPORTS SUCCESSFUL!")
print("=" * 50)
