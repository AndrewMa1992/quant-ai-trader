"""
模型训练管线

P1-3: Transformer 训练崩溃修复 — NaN/inf 防护 + 显式 float32 转换
"""
from typing import Dict, List, Optional
import numpy as np
from datetime import datetime
from loguru import logger
from backend.config import model_config
from backend.data_engine import MarketDataEngine, DataPipeline

market_data = MarketDataEngine()
pipeline = DataPipeline()


class ModelTrainer:
    """量化基金级模型训练器"""

    def __init__(self, transformer=None, rl_agent=None):
        # ★ 延迟导入避免循环依赖 (trainer → ai_models → trainer)
        from backend.ai_models import TransformerPredictor, TradingRLAgent
        self.transformer = transformer or TransformerPredictor()
        self.rl_agent = rl_agent or TradingRLAgent()
        self.training_history: List[Dict] = []

    def train_all(self, tickers: Optional[List[str]] = None):
        logger.info("=" * 60)
        logger.info("  量化基金级模型训练")
        logger.info("=" * 60)

        # ★ 使用配置的训练参数
        train_count = model_config.TRAIN_TICKERS
        train_period = model_config.TRAIN_PERIOD
        lookback = model_config.TRANSFORMER_LOOKBACK

        if tickers is None:
            # ★ 使用稳定美股列表（S&P 500 成分股，数据可靠）
            tickers = [
                "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK.B", "JPM", "V",
                "JNJ", "WMT", "MA", "PG", "UNH", "HD", "DIS", "BAC", "ADBE", "CRM",
                "NFLX", "INTC", "AMD", "PYPL", "CSCO", "PEP", "KO", "TMO", "ABT", "NKE",
                "MRK", "CVX", "XOM", "COST", "AVGO", "LLY", "ORCL", "QCOM", "TXN", "WFC",
                "VZ", "ACN", "LIN", "MCD", "UPS", "MS", "CAT", "PM", "DHR", "T"
            ]
            tickers = tickers[:train_count]
        logger.info(f"📊 训练: {len(tickers)}只美股 | {train_period}数据 | {lookback}天回看")
        logger.info(f"🏗️ 模型: Transformer ({model_config.TRANSFORMER_D_MODEL_LARGE}d/{model_config.TRANSFORMER_N_LAYERS_LARGE}层/{model_config.TRANSFORMER_N_HEADS_LARGE}头)")

        data_dict = market_data.get_multi_ticker_data(tickers, period=train_period, interval="1d")
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
        """
        P1-3: Transformer 训练 — 增强 NaN/inf 防护 + Walk-forward 验证。

        改进:
        - NaN/posinf/neginf → 安全替换
        - 显式 float32 转换
        - 从简单 80/20 分割升级为 Walk-forward 滚动窗口验证
        - 记录每折验证指标，选择最佳模型
        """
        lookback = model_config.TRANSFORMER_LOOKBACK
        pred_len = 5
        n_splits = model_config.WALK_FORWARD_SPLITS  # = 3
        walk_forward_window = model_config.WALK_FORWARD_WINDOW  # = 252

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

        X = np.array(all_X)
        y = np.array(all_y)
        X = np.nan_to_num(X, nan=0.0, posinf=1.0, neginf=-1.0)
        y = np.nan_to_num(y, nan=0.0, posinf=1.0, neginf=-1.0)
        X = X.astype(np.float32)
        y = y.astype(np.float32)

        total_samples = len(X)
        logger.info(f"Transformer Walk-forward 训练: total={total_samples} samples, "
                    f"splits={n_splits}, window={walk_forward_window}")

        # Walk-forward 滚动窗口
        best_val_loss = float("inf")
        best_state = None
        all_val_losses = []

        for fold in range(n_splits):
            # 确定当前折的训练/验证边界
            # 训练: [0, train_end), 验证: [train_end, val_end)
            # 每折验证窗口递增，训练窗口也递增
            fold_size = total_samples // (n_splits + 1)
            train_end = total_samples - (n_splits - fold) * fold_size
            val_end = min(train_end + fold_size, total_samples)

            if train_end <= lookback or val_end - train_end < 50:
                continue

            X_train = X[:train_end]
            y_train = y[:train_end]
            X_val = X[train_end:val_end]
            y_val = y[train_end:val_end]

            # 仅第一折完整训练，后续折增量微调
            epochs = 30 if fold == 0 else 10
            lr = 1e-4 if fold == 0 else 5e-5

            logger.info(f"  Fold {fold+1}/{n_splits}: train={X_train.shape}, val={X_val.shape} (epochs={epochs}, lr={lr})")

            val_loss = self.transformer.train(
                X_train, y_train, X_val, y_val,
                n_vars=X.shape[2], epochs=epochs, lr=lr, return_val_loss=True,
            )

            all_val_losses.append(val_loss)
            logger.info(f"  Fold {fold+1} val_loss: {val_loss:.6f}")

            # 跟踪最佳模型
            if val_loss is not None and val_loss < best_val_loss:
                best_val_loss = val_loss
                import copy
                best_state = copy.deepcopy(self.transformer.model.state_dict())

        # 恢复最佳模型状态
        if best_state is not None:
            self.transformer.model.load_state_dict(best_state)
            logger.info(f"✅ Walk-forward 最佳模型: val_loss={best_val_loss:.6f}")

        # 汇总
        if all_val_losses:
            avg_loss = np.mean(all_val_losses)
            logger.info(f"📊 Walk-forward 汇总: avg_val_loss={avg_loss:.6f}, "
                        f"folds={len(all_val_losses)}")
        else:
            logger.warning("Walk-forward 无法生成有效折叠，回退到简单训练")
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
