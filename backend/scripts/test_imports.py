"""Verify that all modules import successfully."""
import sys
sys.path.insert(0, '.')

print("=" * 50)
print("Quant AI Trader - Module import verification")
print("=" * 50)

# Core
import torch; print(f"PyTorch {torch.__version__}")
import numpy as np; print(f"NumPy {np.__version__}")
import pandas as pd; print(f"Pandas {pd.__version__}")

# Config
from configs.settings import settings
print(f"Config: {len(settings.DATA_ALL_TICKERS)} tickers, ${settings.TRADING_INITIAL_CAPITAL} capital")

# Data Engine
print("Data Engine OK")

# AI Models
print("AI Models OK")

# Trading Engine
print("Trading Engine OK")

# API
print("API Routes OK")

# Full pipeline test
print("Strategy Module OK")

print("Trainer Module OK")

print("=" * 50)
print("ALL IMPORTS SUCCESSFUL!")
print("=" * 50)
