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
    Cross-stock correlation analyzer.
    - Builds a stock graph from recent price correlation
    - Identifies lead/lag relationships
    - Produces a cross-stock signal boost factor
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
        """Return the sector for a ticker."""
        return self.SECTOR_MAP.get(ticker, "Other")

    def compute_sector_momentum(
        self,
        tickers: List[str],
        features_dict: Dict[str, np.ndarray],
    ) -> Dict[str, float]:
        """
        Compute momentum for each sector.
        Returns: {sector: momentum_score}
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
        Generate a cross-stock enhancement signal for one ticker.
        Returns: {boost_factor, sector_momentum, peer_correlation, signal}
        """
        sector = self.get_sector(ticker)
        sector_momentum = self._sector_momentum.get(sector, 0.0)

        # Find same-sector peers
        peers = [t for t in all_tickers if self.get_sector(t) == sector and t != ticker]

        # Correlation versus peers
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

        # Signal boost logic
        # Strong sector momentum + positive peer correlation → boost
        # Weak sector momentum + positive peer correlation → dampen
        boost = 1.0 + sector_momentum * 2.0 + avg_peer_corr * 0.5
        boost = np.clip(boost, 0.5, 2.0)

        # Signal direction
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
        """Return sectors with the strongest momentum."""
        sorted_sectors = sorted(
            self._sector_momentum.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        return sorted_sectors[:n]

    def get_sector_allocation_hint(self, n_sectors: int = 3) -> Dict[str, float]:
        """
        Suggest allocations from sector momentum.
        Returns: {sector: allocation_pct}
        """
        top = self.get_top_sectors(n_sectors)
        total_momentum = sum(abs(m) for _, m in top)
        if total_momentum == 0:
            return {}
        return {sector: abs(momentum) / total_momentum for sector, momentum in top}


# Global instance
cross_stock = CrossStockCorrelation()
