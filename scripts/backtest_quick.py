"""Quick backtest: load models, generate signals on recent data."""
import sys; sys.path.insert(0, r"E:\workbuddyspace\Claw\quant-ai-trader")
from loguru import logger

# Load stock universe
from backend.data_engine.stock_universe import stock_universe
su = stock_universe
su._all_stocks = []
su.build()

# Load models
from services.model_infer_service.inference_engine import InferenceEngine
engine = InferenceEngine()
result = engine.load_models()
logger.info(f"Models loaded: {result}")

# Test on US stocks
us_tickers = su.us_tickers[:20]
logger.info(f"Testing {len(us_tickers)} US stocks...")

signals = engine.generate_signals_batch(
    input_data=us_tickers,
    top_n=5,
    min_threshold=0.05,
    min_confidence=0.3,
)

logger.info(f"Signals generated: {len(signals) if signals else 0}")
if signals:
    for s in signals[:5]:
        logger.info(f"  {s.get('ticker','?')}: signal={s.get('signal',0):.4f}, conf={s.get('confidence',0):.2f}, action={s.get('action','HOLD')}")
else:
    logger.warning("No signals above threshold - models may need retraining")
