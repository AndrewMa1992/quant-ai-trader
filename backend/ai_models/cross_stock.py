"""
Cross-Stock Correlation Layer (Lightweight GNN)
- Builds dynamic correlation graph between stocks
- Generates sector/cluster embeddings for signal enhancement
- Lightweight enough for real-time inference without GPU training
"""
import numpy as np
from typing import Dict, List, Tuple
from collections import defaultdict
from loguru import logger


class CrossStockCorrelation:
    """
    跨股票关联分析器
    - 基于近期价格相关性构建股票关系图
    - 识别领先/滞后关系
    - 生成跨股票信号增强因子
    """

    # Pre-defined sector clusters for US stocks
    SECTOR_CLUSTERS = {
        "Tech": ["AAPL","MSFT","GOOGL","AMZN","NVDA","META","NFLX","ADBE","CRM","CSCO",
                 "INTC","AMD","QCOM","TXN","AVGO","ORCL","IBM","NOW","SNOW","MU",
                 "AMAT","LRCX","ADI","PANW","ZS","CRWD","NET","PLTR","DDOG","FTNT"],
        "Finance": ["JPM","V","MA","BAC","WFC","GS","MS","AXP","BLK","SCHW",
                    "C","USB","PNC","COF","BK","TFC","AIG","MET","BX","CME"],
        "Healthcare": ["UNH","JNJ","PFE","MRK","ABT","TMO","DHR","LLY","ABBV","BMY",
                       "AMGN","GILD","ISRG","REGN","VRTX","CI","HUM","ZTS","BSX","EW"],
        "Consumer": ["WMT","PG","COST","KO","PEP","HD","NKE","MCD","SBUX","DIS",
                     "LOW","TGT","TJX","ROST","DG","LULU","CMG","YUM","EL","MDLZ"],
        "Industrial": ["XOM","CVX","CAT","DE","BA","GE","HON","LMT","UPS","RTX",
                       "UNP","FDX","DAL","LUV","COP","EOG","SLB","MMM","EMR","ETN"],
        "Semiconductor": ["NVDA","AMD","INTC","QCOM","TXN","AVGO","MU","AMAT","LRCX",
                         "ADI","MRVL","KLAC","TER","ASML","TSM"],
        "ETF": ["SPY","QQQ","IWM","DIA","XLF","XLE","XLK","XLV","XLI","XLY"],
    }

    # Reverse lookup: ticker -> sector
    SECTOR_MAP: Dict[str, str] = {}
    for sector, tickers in SECTOR_CLUSTERS.items():
        for t in tickers:
            SECTOR_MAP[t] = sector

    def __init__(self, lookback_days: int = 20):
        self.lookback = lookback_days
        self._correlation_cache: Dict[str, np.ndarray] = {}
        self._sector_momentum: Dict[str, float] = {}

    def get_sector(self, ticker: str) -> str:
        """获取股票所属行业"""
        return self.SECTOR_MAP.get(ticker, "Other")

    def compute_sector_momentum(
        self,
        tickers: List[str],
        features_dict: Dict[str, np.ndarray],
    ) -> Dict[str, float]:
        """
        计算各行业动量
        返回: {sector: momentum_score}
        """
        sector_returns: Dict[str, List[float]] = defaultdict(list)

        for ticker in tickers:
            features = features_dict.get(ticker)
            if features is None or features.shape[0] < self.lookback:
                continue

            sector = self.get_sector(ticker)
            recent = features[-self.lookback:, 0]  # close prices
            if len(recent) >= 5:
                ret = (recent[-1] - recent[0]) / (recent[0] + 1e-8)
                sector_returns[sector].append(ret)

        for sector, returns in sector_returns.items():
            if returns:
                self._sector_momentum[sector] = float(np.mean(returns))
            else:
                self._sector_momentum[sector] = 0.0

        return dict(self._sector_momentum)

    def get_cross_stock_signal(
        self,
        ticker: str,
        all_tickers: List[str],
        features_dict: Dict[str, np.ndarray],
    ) -> Dict:
        """
        为单个股票生成跨股票增强信号
        返回: {boost_factor, sector_momentum, peer_correlation, signal}
        """
        sector = self.get_sector(ticker)
        sector_momentum = self._sector_momentum.get(sector, 0.0)

        # 找同行业 peers
        peers = [t for t in all_tickers if self.get_sector(t) == sector and t != ticker]

        # 计算与 peers 的相关性
        features = features_dict.get(ticker)
        if features is None or features.shape[0] < self.lookback:
            return {"boost_factor": 1.0, "sector_momentum": 0.0,
                    "peer_correlation": 0.0, "signal": "neutral"}

        own_returns = np.diff(features[-self.lookback:, 0]) / (features[-self.lookback:-1, 0] + 1e-8)

        peer_corrs = []
        for peer in peers[:10]:  # max 10 peers
            pf = features_dict.get(peer)
            if pf is None or pf.shape[0] < self.lookback:
                continue
            peer_returns = np.diff(pf[-self.lookback:, 0]) / (pf[-self.lookback:-1, 0] + 1e-8)
            if len(own_returns) == len(peer_returns):
                corr = np.corrcoef(own_returns, peer_returns)[0, 1]
                if not np.isnan(corr):
                    peer_corrs.append(corr)

        avg_peer_corr = float(np.mean(peer_corrs)) if peer_corrs else 0.0

        # 信号增强逻辑
        # 如果行业动量强 + 与 peers 正相关 → 增强信号
        # 如果行业动量弱 + 与 peers 正相关 → 减弱信号
        boost = 1.0 + sector_momentum * 2.0 + avg_peer_corr * 0.5
        boost = np.clip(boost, 0.5, 2.0)

        # 信号方向
        if sector_momentum > 0.02 and avg_peer_corr > 0.3:
            gnn_signal = "buy"
            gnn_strength = min(abs(sector_momentum) * 10 + avg_peer_corr, 1.0)
        elif sector_momentum < -0.02 and avg_peer_corr > 0.3:
            gnn_signal = "sell"
            gnn_strength = min(abs(sector_momentum) * 10 + avg_peer_corr, 1.0)
        else:
            gnn_signal = "neutral"
            gnn_strength = 0.0

        return {
            "boost_factor": float(boost),
            "sector_momentum": sector_momentum,
            "peer_correlation": avg_peer_corr,
            "signal": gnn_signal,
            "strength": gnn_strength,
            "sector": sector,
            "peers_analyzed": len(peer_corrs),
        }

    def get_top_sectors(self, n: int = 3) -> List[Tuple[str, float]]:
        """获取动量最强的行业"""
        sorted_sectors = sorted(
            self._sector_momentum.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        return sorted_sectors[:n]

    def get_sector_allocation_hint(self, n_sectors: int = 3) -> Dict[str, float]:
        """
        基于行业动量给出配置建议
        返回: {sector: allocation_pct}
        """
        top = self.get_top_sectors(n_sectors)
        total_momentum = sum(abs(m) for _, m in top)
        if total_momentum == 0:
            return {}
        return {sector: abs(momentum) / total_momentum for sector, momentum in top}


# Global instance
cross_stock = CrossStockCorrelation()
