"""
策略管理器 - 信号生成与策略调度中枢 (v3 - GNN + RL Enhanced)
整合 AI 模型、技术指标、情绪分析、跨股票关联生成统一交易信号
"""
from typing import Dict, List, Optional, Callable
from datetime import datetime
import numpy as np
from loguru import logger

from configs.settings import settings
from backend.data_engine import DataPipeline
from backend.ai_models import (
    TransformerPredictor, TradingRLAgent, SentimentAnalyzer,
    SignalEnsemble,
)
from backend.ai_models import CrossStockCorrelation, cross_stock
from backend.ai_models import GATSignalGenerator, gat_network
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
        执行一次完整的分析交易循环 (v3 Enhanced)

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

        # 0. 跨股票关联分析（一次性计算，所有股票共享）
        features_dict = {t: data_dict[t]["features"] for t in tickers if t in data_dict}
        try:
            cross_stock.compute_sector_momentum(tickers, features_dict)
        except (AttributeError, TypeError, Exception):
            pass  # stub mode 或模块未完全加载时静默跳过
        # GAT 行业动量计算
        try:
            gat_network.compute_sector_momentum(tickers, features_dict)
        except Exception:
            pass

        for ticker in tickers:
            if ticker not in data_dict or ticker not in prices:
                continue

            signal = self._analyze_single_ticker(ticker, data_dict, prices, tickers, features_dict)
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
        all_tickers: List[str] = None,
        features_dict: Dict[str, np.ndarray] = None,
    ) -> Optional[Dict]:
        """分析单只股票 (v3: RL + GNN cross-stock enhanced)"""
        features = data_dict.get(ticker, {}).get("features")
        if features is None:
            return None

        price = prices.get(ticker, 0.0)
        signals = {}

        # 1. Transformer 预测信号
        if self.transformer.is_ready() and len(features) >= settings.MODEL_TRANSFORMER_LOOKBACK:
            try:
                input_seq = features[-settings.MODEL_TRANSFORMER_LOOKBACK:]
                if input_seq.shape[0] == settings.MODEL_TRANSFORMER_LOOKBACK:
                    pred = self.transformer.predict(input_seq)
                    signals["transformer"] = {
                        "direction": pred["direction"],
                        "strength": pred["confidence"],
                        "confidence": pred["confidence"],
                        "prediction": pred,
                    }
            except Exception as e:
                logger.warning(f"⚠️ {ticker} Transformer 预测失败: {e}")

        # 2. RL Agent 信号（v3: 已启用，单股推理）
        if self.rl_agent.is_ready() and len(features) >= 30:
            try:
                from backend.trading_engine.portfolio import PortfolioManager
                pos_pct = 0.0
                rl_signal = self.rl_agent.predict_signal(
                    features=features,
                    ticker=ticker,
                    price=price,
                    position_pct=pos_pct,
                )
                if rl_signal.get("confidence", 0) > 0:
                    signals["rl_agent"] = rl_signal
            except Exception as e:
                logger.debug(f"⚠️ {ticker} RL 推理跳过: {e}")

        # 3. 跨股票关联信号（GAT v2 + GNN-lite fallback）
        if all_tickers and features_dict:
            try:
                # 优先使用 GAT
                if getattr(gat_network, 'model', None) is not None:
                    cs = gat_network.get_cross_stock_signal(ticker, all_tickers, features_dict)
                else:
                    cs = cross_stock.get_cross_stock_signal(ticker, all_tickers, features_dict)
                if cs.get("strength", 0) > 0 or cs.get("boost_factor", 1.0) != 1.0:
                    signals["cross_stock"] = cs
            except Exception as e:
                logger.debug(f"⚠️ {ticker} 跨股票分析跳过: {e}")

        # 4. 技术指标信号
        tech_signal = self._generate_technical_signal(features)
        signals["technical"] = tech_signal

        # 5. 情绪信号
        sentiment_signal = self.sentiment.get_signal(ticker)
        signals["sentiment"] = sentiment_signal

        # 信号融合（带跨股票增强因子）
        if not signals:
            return None

        cross_stock_boost = 1.0
        if "cross_stock" in signals:
            cross_stock_boost = signals["cross_stock"].get("boost_factor", 1.0)

        fused = self.ensemble.fuse_signals(signals, cross_stock_boost)

        # 防御性访问：fuse_signals 可能返回异常格式（stub 模式等）
        if not fused or not isinstance(fused, dict):
            return {
                "decision": "hold",
                "strength": 0.0,
                "confidence": 0.0,
                "position_size": 0.0,
                "ensemble_score": 0.0,
                "details": {},
            }

        return {
            "decision": fused.get("decision", "hold"),
            "strength": fused.get("strength", 0.0),
            "confidence": fused.get("confidence", 0.0),
            "position_size": fused.get("position_size", 0.0),
            "ensemble_score": fused.get("ensemble_score", 0.0),
            "details": fused.get("details", {}),
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
        """构建 RL 状态（仅用数值特征，过滤非数值）"""
        flat = features.flatten()
        # 只保留纯数值，过滤任何字符串或 NaN
        flat = pd.Series(flat[pd.notna(flat)]).apply(lambda x: float(x) if isinstance(x, (int, float, np.number)) else np.nan).dropna().values
        flat = flat[-1000:] if len(flat) > 1000 else flat
        state = np.concatenate([
            flat,
            [float(prices.get(ticker, 0.0))],
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
