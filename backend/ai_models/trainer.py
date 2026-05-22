"""
模型训练管线
"""
from typing import Dict, List, Optional
import numpy as np
from datetime import datetime
from loguru import logger
from backend.config import model_config
from backend.data_engine import MarketDataEngine, DataPipeline
from backend.ai_models import TransformerPredictor, TradingRLAgent

market_data = MarketDataEngine()
pipeline = DataPipeline()


class ModelTrainer:
    def __init__(self, transformer=None, rl_agent=None):
        self.transformer = transformer or TransformerPredictor()
        self.rl_agent = rl_agent or TradingRLAgent()
        self.training_history: List[Dict] = []

    def train_all(self, tickers: Optional[List[str]] = None):
        logger.info("=" * 50)
        logger.info("开始全面模型训练")
        logger.info("=" * 50)
        tickers = tickers or ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"]

        data_dict = market_data.get_multi_ticker_data(tickers, period="2y", interval="1d")
        if not data_dict:
            logger.error("无数据，训练终止")
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
            logger.info(f"  {ticker}: {features.shape[0]} 行, {features.shape[1]} 特征")

        if not features_list:
            logger.error("特征工程失败")
            return

        min_length = min(features_list)

        try:
            self._train_transformer(processed_dict, tickers, min_length)
        except Exception as e:
            logger.error(f"Transformer 训练失败: {e}")

        try:
            self._train_rl_agent(processed_dict, tickers, min_length)
        except Exception as e:
            logger.error(f"RL 训练失败: {e}")

        self.training_history.append({
            "timestamp": datetime.now().isoformat(),
            "tickers": tickers, "samples": min_length,
            "transformer_trained": self.transformer.is_ready(),
            "rl_trained": self.rl_agent.is_ready(),
        })
        logger.info("训练完成！")

    def load_or_retrain(self):
        trans_loaded = self.transformer.load()
        rl_loaded = self.rl_agent.load()
        if not trans_loaded or not rl_loaded:
            logger.info("模型不存在，如需训练请调用 train_all()")
        return self.transformer.is_ready(), self.rl_agent.is_ready()

    def _train_transformer(self, processed_dict, tickers, min_length):
        lookback = model_config.TRANSFORMER_LOOKBACK
        pred_len = 5
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
            logger.warning(f"样本不足 ({len(all_X)})")
            return
        X, y = np.array(all_X), np.array(all_y)
        from sklearn.model_selection import train_test_split
        X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, shuffle=False)
        self.transformer.train(X_train, y_train, X_val, y_val, n_vars=X.shape[2])
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
            # 保存收盘价
            close_dict[ticker] = processed_dict[ticker]["close"].values[:min_length]
        if not df_dict:

            return
        self.rl_agent.create_env(df_dict, close_dict=close_dict,
                                       feature_dim=min(40, list(df_dict.values())[0].shape[1]))
        self.rl_agent.train(total_timesteps=30000)
        self.rl_agent.save()

    def get_training_summary(self):
        return {
            "transformer_ready": self.transformer.is_ready(),
            "rl_ready": self.rl_agent.is_ready(),
            "history_count": len(self.training_history),
        }
