"""Quick GPU training for all models on RTX3060 with recent market data."""
import sys; sys.path.insert(0, r"E:\workbuddyspace\Claw\quant-ai-trader")
import torch, os
from loguru import logger

os.environ["QAT_TRAIN_DEVICE"] = "cuda"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
logger.info(f"Training on {DEVICE} ({torch.cuda.get_device_name(0) if DEVICE=='cuda' else 'CPU'})")

# Load trainers
from services.model_train_service.trainers.gbdt_trainer import GBDTTrainer
from services.model_train_service.trainers.tcn_trainer import TCNTrainer  
from services.model_train_service.trainers.transformer_trainer import TransformerTrainer
from services.model_train_service.trainers.tft_trainer import TFTTrainer

# Quick train on small subset for speed
from backend.data_engine.stock_universe import stock_universe
su = stock_universe; su._all_stocks = []; su.build()
tickers = su.us_tickers[:30]  # Train on top 30 US stocks

trainers = {
    "gbdt": GBDTTrainer(device=DEVICE),
    "tcn": TCNTrainer(device=DEVICE),
    "transformer": TransformerTrainer(device=DEVICE),
    "tft": TFTTrainer(device=DEVICE),
}

for name, trainer in trainers.items():
    try:
        logger.info(f"Training {name} on {len(tickers)} tickers...")
        trainer.train(tickers=tickers, epochs=10, batch_size=32)
        trainer.save(f"data/models/{name}_v2_live.pt" if name != "gbdt" else f"data/models/{name}_v2_live.joblib")
        logger.info(f"✅ {name} trained + saved")
    except Exception as e:
        logger.error(f"❌ {name} training failed: {e}")

logger.info("GPU training complete")
