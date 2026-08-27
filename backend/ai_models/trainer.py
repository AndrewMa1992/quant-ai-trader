"""
Model training pipeline.

P1-3: Transformer crash fix — NaN/inf guards + explicit float32 conversion
"""
from typing import Dict, List, Optional
import numpy as np
from datetime import datetime
from loguru import logger
from configs.settings import settings
from backend.data_engine import MarketDataEngine, DataPipeline

market_data = MarketDataEngine()
pipeline = DataPipeline()


class ModelTrainer:
    """Institutional-grade model trainer."""

    def __init__(self, transformer=None, rl_agent=None):
        # Delayed import to avoid a circular dependency (trainer → ai_models → trainer)
        from backend.ai_models import TransformerPredictor, TradingRLAgent
        self.transformer = transformer or TransformerPredictor()
        self.rl_agent = rl_agent or TradingRLAgent()
        self.training_history: List[Dict] = []

    def train_all(self, tickers: Optional[List[str]] = None):
        logger.info("=" * 60)
        logger.info("  Institutional-grade model training")
        logger.info("=" * 60)

        # Use configured training parameters
        train_count = settings.MODEL_TRAIN_TICKERS
        train_period = settings.MODEL_TRAIN_PERIOD
        lookback = settings.MODEL_TRANSFORMER_LOOKBACK

        if tickers is None:
            # Use a stable US list (S&P 500 constituents; reliable data)
            tickers = [
                "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK.B", "JPM", "V",
                "JNJ", "WMT", "MA", "PG", "UNH", "HD", "DIS", "BAC", "ADBE", "CRM",
                "NFLX", "INTC", "AMD", "PYPL", "CSCO", "PEP", "KO", "TMO", "ABT", "NKE",
                "MRK", "CVX", "XOM", "COST", "AVGO", "LLY", "ORCL", "QCOM", "TXN", "WFC",
                "VZ", "ACN", "LIN", "MCD", "UPS", "MS", "CAT", "PM", "DHR", "T"
            ]
            tickers = tickers[:train_count]
        logger.info(f"📊 Training: {len(tickers)} US names | {train_period} data | {lookback}-day lookback")
        logger.info(f"🏗️ Model: Transformer ({settings.MODEL_TRANSFORMER_D_MODEL_LARGE}d/{settings.MODEL_TRANSFORMER_N_LAYERS_LARGE} layers/{settings.MODEL_TRANSFORMER_N_HEADS_LARGE} heads)")

        data_dict = market_data.get_multi_ticker_data(tickers, period=train_period, interval="1d")
        if not data_dict:
            logger.error("No data; aborting training")
            return

        processed_dict = {}
        features_list = []
        for ticker, df in data_dict.items():
            if df.empty:
                continue
            processed = pipeline.process(df)
            processed_dict[ticker] = processed
            fcols = [c for c in pipeline.FEATURE_COLUMNS if c in processed.columns]
            features = processed[fcols].values
            processed_dict[f"{ticker}_features"] = features
            features_list.append(features.shape[0])
            logger.info(f"  {ticker}: {features.shape[0]} rows, {features.shape[1]} features")

        if not features_list:
            logger.error("Feature engineering failed")
            return

        min_length = min(features_list)

        try:
            self._train_transformer(processed_dict, tickers, min_length)
        except Exception as e:
            logger.error(f"Transformer training failed: {e}")
            import traceback
            traceback.print_exc()

        try:
            self._train_rl_agent(processed_dict, tickers, min_length)
        except Exception as e:
            logger.error(f"RL training failed: {e}")

        self.training_history.append({
            "timestamp": datetime.now().isoformat(),
            "tickers": tickers, "samples": min_length,
            "transformer_trained": self.transformer.is_ready(),
            "rl_trained": self.rl_agent.is_ready(),
        })
        logger.info("Training complete.")

    def load_or_retrain(self):
        trans_loaded = self.transformer.load()
        rl_loaded = self.rl_agent.load()
        if not trans_loaded or not rl_loaded:
            logger.info("Models not found; call train_all() to train")
        return self.transformer.is_ready(), self.rl_agent.is_ready()

    def _train_transformer(self, processed_dict, tickers, min_length):
        """
        P1-3: Transformer training — stronger NaN/inf guards + walk-forward validation.

        Improvements:
        - NaN/posinf/neginf → safe replacement
        - Explicit float32 conversion
        - Walk-forward rolling-window validation
        - FP16 mixed precision (CUDA)
        - CosineAnnealingWarmRestarts + linear warmup
        - Record per-fold validation metrics and keep the best model
        """
        import torch

        lookback = settings.MODEL_TRANSFORMER_LOOKBACK
        pred_len = 5
        n_splits = settings.MODEL_WALK_FORWARD_SPLITS
        walk_forward_window = settings.MODEL_WALK_FORWARD_WINDOW

        # GPU mixed-precision probe
        use_amp = (self.transformer.device.type == 'cuda') if hasattr(self.transformer, 'device') else False
        if use_amp:
            logger.info("🚀 FP16 mixed-precision training enabled (CUDA)")

        all_X, all_y = [], []
        for ticker in tickers:
            key = f"{ticker}_features"
            if key not in processed_dict:
                continue
            data = processed_dict[key][:min_length]
            close = processed_dict[ticker]["close"].values[:min_length]
            for i in range(lookback, len(data) - pred_len):
                all_X.append(data[i - lookback:i])
                all_y.append(close[i:i + pred_len])
        if len(all_X) < 100:
            logger.warning(f"Insufficient samples ({len(all_X)})")
            return

        X = np.array(all_X)
        y = np.array(all_y)
        X = np.nan_to_num(X, nan=0.0, posinf=1.0, neginf=-1.0)
        y = np.nan_to_num(y, nan=0.0, posinf=1.0, neginf=-1.0)
        X = X.astype(np.float32)
        y = y.astype(np.float32)

        total_samples = len(X)
        logger.info(f"Transformer walk-forward training: total={total_samples} samples, "
                    f"splits={n_splits}, window={walk_forward_window}")

        # Walk-forward rolling window
        best_val_loss = float("inf")
        best_state = None
        all_val_losses = []

        for fold in range(n_splits):
            fold_size = total_samples // (n_splits + 1)
            train_end = total_samples - (n_splits - fold) * fold_size
            val_end = min(train_end + fold_size, total_samples)

            if train_end <= lookback or val_end - train_end < 50:
                continue

            X_train = X[:train_end]
            y_train = y[:train_end]
            X_val = X[train_end:val_end]
            y_val = y[train_end:val_end]

            # Train each fold for the full epoch count
            epochs = settings.MODEL_TRANSFORMER_EPOCHS
            lr = settings.MODEL_TRANSFORMER_LEARNING_RATE

            logger.info(f"  Fold {fold+1}/{n_splits}: train={X_train.shape}, val={X_val.shape} "
                        f"(epochs={epochs}, lr={lr:.2e}, amp={use_amp})")

            val_loss = self.transformer.train(
                X_train, y_train, X_val, y_val,
                n_vars=X.shape[2], epochs=epochs, lr=lr, return_val_loss=True,
                use_amp=use_amp,
            )

            all_val_losses.append(val_loss)
            logger.info(f"  Fold {fold+1} val_loss: {val_loss:.6f}")

            # Track the best model
            if val_loss is not None and val_loss < best_val_loss:
                best_val_loss = val_loss
                import copy
                best_state = copy.deepcopy(self.transformer.model.state_dict())

        # Restore best-model weights
        if best_state is not None:
            self.transformer.model.load_state_dict(best_state)
            logger.info(f"✅ Walk-forward best model: val_loss={best_val_loss:.6f}")

        # Summary
        if all_val_losses:
            avg_loss = np.mean(all_val_losses)
            logger.info(f"📊 Walk-forward summary: avg_val_loss={avg_loss:.6f}, "
                        f"folds={len(all_val_losses)}")
        else:
            logger.warning("Walk-forward produced no valid folds; falling back to simple training")
            from sklearn.model_selection import train_test_split
            X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, shuffle=False)
            self.transformer.train(X_train, y_train, X_val, y_val, n_vars=X.shape[2],
                                   use_amp=use_amp)

        self.transformer.save()

    def _train_rl_agent(self, processed_dict, tickers, min_length):
        df_dict = {}
        close_dict = {}
        for ticker in tickers:
            key = f"{ticker}_features"
            if key not in processed_dict:
                continue
            data = processed_dict[key][:min_length]
            data = np.nan_to_num(data, nan=0.0, posinf=1.0, neginf=-1.0)
            df_dict[ticker] = data
            # Persist close prices
            close_dict[ticker] = processed_dict[ticker]["close"].values[:min_length]
        if not df_dict:
            return
        self.rl_agent.create_env(df_dict, close_dict=close_dict,
                                       feature_dim=min(40, list(df_dict.values())[0].shape[1]))
        self.rl_agent.train(total_timesteps=settings.MODEL_RL_TOTAL_TIMESTEPS)
        self.rl_agent.save()

    def get_training_summary(self):
        return {
            "transformer_ready": self.transformer.is_ready(),
            "rl_ready": self.rl_agent.is_ready(),
            "history_count": len(self.training_history),
        }
