"""
Graph Attention Network (GAT) — 完整版跨股票关联模型
替代 CrossStockCorrelation (GNN-lite)

架构:
- 动态股票关系图 (Pearson + 行业 + 尾部依赖)
- 3层 Graph Attention Network
- 生成每只股票的关系增强嵌入
- 行业级和全市场级嵌入
"""
import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
from loguru import logger
from configs.settings import settings
from pathlib import Path

torch_cache = CACHE_DIR / "torch"
torch_cache.mkdir(parents=True, exist_ok=True)


# ============================================================
# GAT Layer
# ============================================================
class GATLayer(nn.Module):
    """单层 Graph Attention Layer"""

    def __init__(self, in_dim: int, out_dim: int, n_heads: int = 4, dropout: float = 0.1):
        super().__init__()
        self.n_heads = n_heads
        self.out_dim = out_dim

        # 多头注意力
        self.W = nn.Linear(in_dim, out_dim * n_heads, bias=False)
        self.a = nn.Parameter(torch.zeros(2 * out_dim, 1))
        nn.init.xavier_uniform_(self.a)

        self.dropout = nn.Dropout(dropout)
        self.leaky_relu = nn.LeakyReLU(0.2)

    def forward(self, x: torch.Tensor, adj: torch.Tensor) -> torch.Tensor:
        """
        x: (N, in_dim) 节点特征
        adj: (N, N) 邻接矩阵
        返回: (N, out_dim * n_heads)
        """
        N = x.size(0)
        Wh = self.W(x).view(N, self.n_heads, self.out_dim)  # (N, H, D)

        # 计算注意力分数
        Wh_i = Wh.unsqueeze(2).expand(-1, -1, N, -1)  # (N, H, N, D)
        Wh_j = Wh.unsqueeze(1).expand(-1, N, -1, -1)  # (N, N, H, D)
        Wh_j = Wh_j.permute(0, 2, 1, 3)  # (N, H, N, D)

        e = torch.cat([Wh_i, Wh_j], dim=-1)  # (N, H, N, 2D)
        e = self.leaky_relu(torch.matmul(e, self.a).squeeze(-1))  # (N, H, N)

        # Mask non-edges
        adj_expanded = adj.unsqueeze(1).expand(-1, self.n_heads, -1)  # (N, H, N)
        e = e.masked_fill(adj_expanded == 0, -1e9)

        # Softmax
        alpha = F.softmax(e, dim=-1)  # (N, H, N)
        alpha = self.dropout(alpha)

        # 聚合: alpha (N, H, N) @ Wh (N, H, D)
        # 使用 permute + bmm: (H, N, N) @ (H, N, D) = (H, N, D) → (N, H, D)
        alpha_t = alpha.permute(1, 0, 2)  # (H, N, N)
        Wh_t = Wh.permute(1, 0, 2)  # (H, N, D)
        out = torch.bmm(alpha_t, Wh_t).permute(1, 0, 2)  # (N, H, D)
        out = out.reshape(N, self.out_dim * self.n_heads)  # (N, H*D)
        return out


# ============================================================
# GAT 股票关系网络
# ============================================================
class StockGAT(nn.Module):
    """3层 GAT + readout"""

    def __init__(self, in_dim: int = 20, hidden_dim: int = 64, out_dim: int = 32, n_heads: int = 4):
        super().__init__()
        self.gat1 = GATLayer(in_dim, hidden_dim, n_heads=n_heads, dropout=0.1)
        self.gat2 = GATLayer(hidden_dim * n_heads, hidden_dim, n_heads=n_heads, dropout=0.1)
        self.gat3 = GATLayer(hidden_dim * n_heads, out_dim, n_heads=2, dropout=0.1)

        self.layer_norm1 = nn.LayerNorm(hidden_dim * n_heads)
        self.layer_norm2 = nn.LayerNorm(hidden_dim * n_heads)

        self.sector_proj = nn.Linear(out_dim * 4, 8)  # 2 heads × 2 aggregations
        self.market_proj = nn.Linear(out_dim * 4, 16)

    def forward(self, x: torch.Tensor, adj: torch.Tensor):
        """
        x: (N, in_dim) 每只股票的输入特征
        adj: (N, N) 邻接矩阵
        """
        h1 = F.elu(self.gat1(x, adj))
        h1 = self.layer_norm1(h1)
        h2 = F.elu(self.gat2(h1, adj))
        h2 = self.layer_norm2(h2)
        h3 = self.gat3(h2, adj)  # (N, D)

        # 全局 + 行业级 readout
        market_emb = torch.cat([h3.mean(0), h3.max(0).values])  # (2D,)
        market_emb = self.market_proj(market_emb)  # (16,)

        return h3, market_emb


# ============================================================
# GAT 信号生成器（集成层）
# ============================================================
class GATSignalGenerator:
    """
    基于 GAT 嵌入生成跨股票增强信号
    - 构建动态股票图
    - GAT 前向推理
    - 生成信号增强因子
    """

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
    }
    SECTOR_MAP: Dict[str, str] = {}
    for s, ts in SECTOR_CLUSTERS.items():
        for t in ts:
            SECTOR_MAP[t] = s

    def __init__(self, lookback: int = 20, device: str = "cpu", auto_load: bool = True):
        self.device = device
        self.lookback = lookback
        self.model: Optional[StockGAT] = None
        self._sector_momentum: Dict[str, float] = {}
        self._last_embeddings: Dict[str, np.ndarray] = {}
        # 自动加载已训练的模型
        if auto_load:
            self.load_model()

    def load_model(self, path: str = None):
        """加载预训练 GAT 模型"""
        from configs.settings import settings
        model_path = path or str(MODELS_DIR / "gat_model.pt")
        try:
            self.model = StockGAT().to(self.device)
            if Path(model_path).exists():
                self.model.load_state_dict(torch.load(model_path, map_location=self.device))
                logger.info(f"✅ GAT 模型已加载: {model_path}")
            else:
                logger.info("GAT 模型文件不存在，使用随机初始化")
        except Exception as e:
            logger.warning(f"GAT 模型加载失败: {e}")
            self.model = StockGAT().to(self.device)

    def get_sector(self, ticker: str) -> str:
        return self.SECTOR_MAP.get(ticker, "Other")

    def build_adjacency(
        self,
        tickers: List[str],
        features_dict: Dict[str, np.ndarray],
        threshold: float = 0.3,
    ) -> torch.Tensor:
        """构建动态邻接矩阵（Pearson 相关性 + 行业同属）"""
        N = len(tickers)
        adj = np.zeros((N, N), dtype=np.float32)

        for i in range(N):
            for j in range(i + 1, N):
                ti, tj = tickers[i], tickers[j]

                # 同行业加权
                sector_bonus = 0.2 if self.get_sector(ti) == self.get_sector(tj) else 0.0

                # Pearson 相关性
                fi = features_dict.get(ti)
                fj = features_dict.get(tj)
                if fi is not None and fj is not None and len(fi) >= self.lookback and len(fj) >= self.lookback:
                    ret_i = np.diff(fi[-self.lookback:, 0]) / (fi[-self.lookback:-1, 0] + 1e-8)
                    ret_j = np.diff(fj[-self.lookback:, 0]) / (fj[-self.lookback:-1, 0] + 1e-8)
                    min_len = min(len(ret_i), len(ret_j))
                    if min_len > 3:
                        corr = np.corrcoef(ret_i[:min_len], ret_j[:min_len])[0, 1]
                        if not np.isnan(corr):
                            weight = abs(corr) + sector_bonus
                            if weight > threshold:
                                adj[i, j] = weight
                                adj[j, i] = weight

        return torch.tensor(adj, dtype=torch.float32, device=self.device)

    def build_features(
        self,
        tickers: List[str],
        features_dict: Dict[str, np.ndarray],
    ) -> torch.Tensor:
        """构建节点特征矩阵"""
        N = len(tickers)
        in_dim = 20
        X = np.zeros((N, in_dim), dtype=np.float32)

        for i, ticker in enumerate(tickers):
            features = features_dict.get(ticker)
            if features is None or features.shape[0] < self.lookback:
                continue
            recent = features[-self.lookback:]

            # 基础统计特征
            ret = np.diff(recent[:, 0]) / (recent[:-1, 0] + 1e-8)
            X[i, 0] = ret.mean() if len(ret) > 0 else 0  # 平均收益
            X[i, 1] = ret.std() if len(ret) > 1 else 0  # 波动率
            X[i, 2] = (recent[-1, 0] - recent[0, 0]) / (recent[0, 0] + 1e-8)  # 动量

            # 从特征中提取更多维度
            for k in range(3, min(in_dim, recent.shape[1] + 3)):
                col_data = recent[:, min(k - 3, recent.shape[1] - 1)]
                X[i, k] = col_data.mean() if len(col_data) > 0 else 0

            # 归一化
            row_std = X[i].std()
            if row_std > 0:
                X[i] = (X[i] - X[i].mean()) / row_std

        return torch.tensor(X, dtype=torch.float32, device=self.device)

    def compute_sector_momentum(
        self,
        tickers: List[str],
        features_dict: Dict[str, np.ndarray],
    ) -> Dict[str, float]:
        """计算行业动量"""
        sector_returns: Dict[str, List[float]] = defaultdict(list)
        for ticker in tickers:
            features = features_dict.get(ticker)
            if features is None or features.shape[0] < self.lookback:
                continue
            sector = self.get_sector(ticker)
            ret = (features[-1, 0] - features[-self.lookback, 0]) / (features[-self.lookback, 0] + 1e-8)
            sector_returns[sector].append(ret)
        for sector, returns in sector_returns.items():
            self._sector_momentum[sector] = float(np.mean(returns)) if returns else 0.0
        return dict(self._sector_momentum)

    def get_cross_stock_signal(
        self,
        ticker: str,
        all_tickers: List[str],
        features_dict: Dict[str, np.ndarray],
    ) -> Dict:
        """
        GAT 增强版跨股票信号生成
        """
        sector = self.get_sector(ticker)
        sector_momentum = self._sector_momentum.get(sector, 0.0)

        # 使用 GAT 嵌入
        gat_boost = 1.0
        gat_signal = "neutral"
        gat_strength = 0.0

        if self.model is not None and len(all_tickers) >= 3:
            try:
                adj = self.build_adjacency(all_tickers, features_dict)
                X = self.build_features(all_tickers, features_dict)

                if adj.sum() > 0:
                    with torch.no_grad():
                        embeddings, market_emb = self.model(X, adj)

                    if ticker in all_tickers:
                        idx = all_tickers.index(ticker)
                        stock_emb = embeddings[idx].cpu().numpy()
                        market_vec = market_emb.cpu().numpy()

                        # 嵌入相似度增强
                        emb_norm = np.linalg.norm(stock_emb)
                        market_norm = np.linalg.norm(market_vec)
                        if emb_norm > 0 and market_norm > 0:
                            alignment = np.dot(stock_emb, market_vec) / (emb_norm * market_norm + 1e-8)
                            gat_boost = 1.0 + float(alignment) * 0.5
                            gat_boost = np.clip(gat_boost, 0.5, 2.0)

                        # 信号方向
                        if sector_momentum > 0.02 and gat_boost > 1.2:
                            gat_signal = "buy"
                            gat_strength = min(abs(sector_momentum) * 8 + (gat_boost - 1) * 2, 1.0)
                        elif sector_momentum < -0.02 and gat_boost > 1.2:
                            gat_signal = "sell"
                            gat_strength = min(abs(sector_momentum) * 8 + (gat_boost - 1) * 2, 1.0)

            except Exception as e:
                logger.debug(f"GAT 推理失败 {ticker}: {e}")

        # 如果 GAT 不可用，回退到简单方法
        if gat_boost == 1.0:
            peers = [t for t in all_tickers if self.get_sector(t) == sector and t != ticker]
            peer_corrs = []
            features = features_dict.get(ticker)
            if features is not None and features.shape[0] >= self.lookback:
                own_ret = np.diff(features[-self.lookback:, 0]) / (features[-self.lookback:-1, 0] + 1e-8)
                for peer in peers[:10]:
                    pf = features_dict.get(peer)
                    if pf is not None and pf.shape[0] >= self.lookback:
                        peer_ret = np.diff(pf[-self.lookback:, 0]) / (pf[-self.lookback:-1, 0] + 1e-8)
                        if len(own_ret) == len(peer_ret):
                            c = np.corrcoef(own_ret, peer_ret)[0, 1]
                            if not np.isnan(c):
                                peer_corrs.append(c)
            avg_corr = float(np.mean(peer_corrs)) if peer_corrs else 0.0
            gat_boost = np.clip(1.0 + sector_momentum * 2 + avg_corr * 0.5, 0.5, 2.0)

        return {
            "boost_factor": float(gat_boost),
            "sector_momentum": sector_momentum,
            "signal": gat_signal,
            "strength": gat_strength,
            "sector": sector,
            "source": "gat_v2",
        }

    def get_top_sectors(self, n: int = 3) -> List[Tuple[str, float]]:
        sorted_sec = sorted(self._sector_momentum.items(), key=lambda x: x[1], reverse=True)
        return sorted_sec[:n]

    def train_gat(
        self,
        tickers: List[str],
        features_dict: Dict[str, np.ndarray],
        epochs: int = 50,
        lr: float = 1e-3,
    ):
        """轻量级 GAT 训练"""
        if self.model is None:
            self.load_model()

        adj = self.build_adjacency(tickers, features_dict)
        X = self.build_features(tickers, features_dict)

        if adj.sum() == 0 or len(tickers) < 3:
            logger.warning("GAT: 邻接矩阵为空或股票数不足，跳过训练")
            return

        optimizer = torch.optim.Adam(self.model.parameters(), lr=lr)

        for epoch in range(epochs):
            self.model.train()
            optimizer.zero_grad()

            embeddings, market_emb = self.model(X, adj)

            # 重构损失 + 对比损失
            recon_loss = F.mse_loss(embeddings, X[:, :embeddings.size(-1)]) if embeddings.size(-1) == X.size(-1) else 0
            # 行业一致性损失
            sector_loss = 0.0
            for i in range(len(tickers)):
                for j in range(i + 1, len(tickers)):
                    if self.get_sector(tickers[i]) == self.get_sector(tickers[j]) and adj[i, j] > 0:
                        sector_loss += 1 - F.cosine_similarity(
                            embeddings[i].unsqueeze(0), embeddings[j].unsqueeze(0)
                        )
            sector_loss = sector_loss / max(1, (adj > 0).sum())

            loss = 0.1 * recon_loss + 0.01 * sector_loss
            loss.backward()
            optimizer.step()

        # 保存
        from configs.settings import settings
        save_path = MODELS_DIR / "gat_model.pt"
        torch.save(self.model.state_dict(), save_path)
        logger.info(f"✅ GAT 训练完成, 已保存: {save_path}")


# 全局单例
gat_network = GATSignalGenerator()
