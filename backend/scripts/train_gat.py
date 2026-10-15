"""
GAT (Graph Attention Network) training script v2.
Trains the cross-stock correlation model from local parquet data.
"""
import sys
import pandas as pd
import numpy as np
from pathlib import Path

PROJ_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJ_ROOT))

from loguru import logger
from backend.data_engine import DataPipeline
from backend.ai_models.gat_network import GATSignalGenerator

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | {message}")

DATA_DIR = PROJ_ROOT / "data" / "daily"


def main():
    logger.info("=" * 50)
    logger.info("  GAT graph-attention training (local parquet)")
    logger.info("=" * 50)

    # 1. Load local parquet data
    logger.info("📂 Loading local data...")
    pipeline = DataPipeline()
    features_dict = {}
    tickers = []

    for parquet_file in sorted(DATA_DIR.glob("*.parquet")):
        ticker = parquet_file.stem
        try:
            df = pd.read_parquet(parquet_file)
            if len(df) < 60:
                continue
            # Normalize column names
            if 'Close' in df.columns:
                df = df.rename(columns={'Close': 'close', 'High': 'high',
                                        'Low': 'low', 'Open': 'open', 'Volume': 'volume'})
            processed = pipeline.process(df)
            fcols = [c for c in pipeline.FEATURE_COLUMNS if c in processed.columns]
            features = processed[fcols].values
            if features.shape[0] < 20:
                continue
            features_dict[ticker] = features
            tickers.append(ticker)
            logger.debug(f"  {ticker:6s}: {features.shape}")
        except Exception as e:
            logger.warning(f"  {ticker}: load failed - {e}")
            continue

    logger.info(f"📊 Valid tickers: {len(tickers)}")

    if len(tickers) < 3:
        logger.error("❌ Not enough valid tickers")
        return

    # 2. Train GAT
    logger.info("🧠 Training GAT (50 epochs)...")
    import torch
    device = "cuda" if torch.cuda.is_available() else ("mps" if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available() else "cpu")
    gat = GATSignalGenerator(lookback=20, device=device)
    gat.train_gat(tickers=tickers, features_dict=features_dict, epochs=50, lr=1e-3)

    # 3. Validate
    logger.info("✅ Validating GAT inference...")
    gat.load_model()
    for ticker in tickers[:8]:
        signal = gat.get_cross_stock_signal(ticker, tickers, features_dict)
        logger.info(f"  {ticker:6s} → boost={signal['boost_factor']:.2f} "
                    f"sector={signal['sector']:12s} momentum={signal['sector_momentum']:.3f} "
                    f"signal={signal['signal']}")

    # 4. Check model file
    from configs.settings import settings
    model_path = settings.MODELS_DIR / "gat_model.pt"
    if model_path.exists():
        logger.info(f"✅ GAT model saved: {model_path} ({model_path.stat().st_size / 1024:.1f} KB)")
    else:
        logger.error("❌ Model save failed")

    logger.info("")
    logger.info("✅ GAT training complete. Cross-stock correlation upgraded from Pearson to GAT.")


if __name__ == "__main__":
    main()
