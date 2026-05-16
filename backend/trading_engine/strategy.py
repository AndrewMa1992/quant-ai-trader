"""
策略管理器 - 信号生成与策略调度中枢
整合 AI 模型、技术指标、情绪分析生成统一交易信号
"""
from typing import Dict, List, Optional, Callable
from datetime import datetime
import numpy as np
from loguru import logger

from backend.config import model_config
from backend.data_engine import DataPipeline
from backend.ai_models import TransformerPredictor, TradingRLAgent, SentimentAnalyzer, SignalEnsemble
from backend.trading_engine.executor import PaperExecutor

pipeline = DataPipeline()


class TradingStrategy:
    """
    交易策略管理器
    - 收集各模型信号
    - 信号融合
    - 定期执行
    - 动态调整
    """

    def __init__(
        self,
        transformer: TransformerPredictor,
        rl_agent: TradingRLAgent,
        sentiment: SentimentAnalyzer,
        ensemble: SignalEnsemble,
        executor: PaperExecutor,
    ):
        self.transformer = transformer
        self.rl_agent = rl_agent
        self.sentiment = sentiment
        self.ensemble = ensemble
        self.executor = executor

        self._analysis_callbacks: List[Callable] = []
        self.last_signals: Dict[str, Dict] = {}
        self._total_cycles = 0

    # ================================================================
    # 主循环
    # ================================================================

    def analyze_and_trade(
        self,
        tickers: List[str],
        data_dict: Dict[str, Dict],
        prices: Dict[str, float],
    ) -> Dict:
        """
        执行一次完整的分析交易循环

        Args:
            tickers: 股票列表
            data_dict: {ticker: {"features": np.ndarray (seq_len, n_vars), ...}}
            prices: {ticker: current_price}

        Returns:
            分析结果
        """
        self._total_cycles += 1
        results = {
            "timestamp": datetime.now().isoformat(),
            "cycle": self._total_cycles,
            "signals": {},
            "trades": [],
        }

        for ticker in tickers:
            if ticker not in data_dict or ticker not in prices:
                continue

            signal = self._analyze_single_ticker(ticker, data_dict, prices)
            if signal:
                results["signals"][ticker] = signal
                self.last_signals[ticker] = signal

        # 执行交易
        trades = self.executor.execute_signal_batch(results["signals"], prices)
        results["trades"] = trades

        # 回调通知
        self._emit_analysis(results)

        return results

    def _analyze_single_ticker(
        self,
        ticker: str,
        data_dict: Dict[str, Dict],
        prices: Dict[str, float],
    ) -> Optional[Dict]:
        """分析单只股票"""
        features = data_dict.get(ticker, {}).get("features")
        if features is None:
            return None

        # 收集各模型信号
        signals = {}

        # 1. Transformer 预测信号
        if self.transformer.is_ready() and len(features) >= model_config.TRANSFORMER_LOOKBACK:
            try:
                # 取最近 seq_len 天
                input_seq = features[-model_config.TRANSFORMER_LOOKBACK:]
                if input_seq.shape[0] == model_config.TRANSFORMER_LOOKBACK:
                    pred = self.transformer.predict(input_seq)
                    signals["transformer"] = {
                        "direction": pred["direction"],
                        "strength": pred["confidence"],
                        "confidence": pred["confidence"],
                        "prediction": pred,
                    }
            except Exception as e:
                logger.warning(f"⚠️ {ticker} Transformer 预测失败: {e}")

        # 2. 技术指标信号
        tech_signal = self._generate_technical_signal(features)
        signals["technical"] = tech_signal

        # 3. 情绪信号
        sentiment_signal = self.sentiment.get_signal(ticker)
        signals["sentiment"] = sentiment_signal

        # 4. RL Agent 信号
        if self.rl_agent.is_ready():
            try:
                state = self._build_rl_state(features, ticker, prices)
                rl_action, _ = self.rl_agent.predict(state)
                signals["rl_agent"] = {
                    "actions": rl_action.tolist() if hasattr(rl_action, "tolist") else [float(rl_action)],
                    "confidence": 0.6,
                }
            except Exception as e:
                logger.warning(f"⚠️ {ticker} RL 预测失败: {e}")

        # 信号融合
        if not signals:
            return None

        fused = self.ensemble.fuse_signals(signals)

        return {
            "decision": fused["decision"],
            "strength": fused["strength"],
            "confidence": fused["confidence"],
            "position_size": fused["position_size"],
            "ensemble_score": fused["ensemble_score"],
            "details": fused["details"],
        }

    def _generate_technical_signal(self, features: np.ndarray) -> Dict:
        """从技术指标生成信号"""
        signal = {"signal": "neutral", "strength": 0.0, "confidence": 0.0}

        if features.shape[0] < 30:
            return signal

        # 使用 rsi 指标（假设 rsi 在特征中的某列）
        # 简化版：取最近几天的收盘价判断趋势
        recent_close = features[-5:, 0] if features.shape[1] > 0 else []

        if len(recent_close) >= 2:
            trend = (recent_close[-1] - recent_close[0]) / (recent_close[0] + 1e-8)

            if trend > 0.02:
                signal = {"signal": "buy", "strength": min(trend * 5, 1.0), "confidence": 0.5}
            elif trend < -0.02:
                signal = {"signal": "sell", "strength": min(abs(trend) * 5, 1.0), "confidence": 0.5}

        return signal

    def _build_rl_state(self, features: np.ndarray, ticker: str, prices: Dict[str, float]) -> np.ndarray:
        """构建 RL 状态"""
        flat = features.flatten()[-1000:] if len(features.flatten()) > 1000 else features.flatten()
        state = np.concatenate([
            flat,
            [prices.get(ticker, 0.0)],
        ])
        return state.astype(np.float32)

    def on_analysis(self, callback: Callable):
        """注册分析回调"""
        self._analysis_callbacks.append(callback)

    def _emit_analysis(self, results: Dict):
        """触发分析回调"""
        for cb in self._analysis_callbacks:
            try:
                cb(results)
            except Exception as e:
                logger.error(f"❌ 分析回调错误: {e}")

    def get_status(self) -> Dict:
        """获取策略状态"""
        return {
            "total_cycles": self._total_cycles,
            "last_signals_count": len(self.last_signals),
            "ensemble_weights": self.ensemble.weights,
            "model_status": {
                "transformer": self.transformer.is_ready(),
                "rl_agent": self.rl_agent.is_ready(),
                "sentiment": True,
            },
        }
