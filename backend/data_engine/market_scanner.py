"""
Market Scanner — 全市场动态品种扫描器

通过 Tiger API 验证股票池中所有品种的可交易性，动态过滤和排名。
替代硬编码股票列表，实现跨市场利益最大化。

功能:
- 从 market_universe 加载全量候选池 (~800只)
- 通过 Tiger API 验证可交易性 (价格>0, 状态正常, 非退市)
- 按流动性/波动率/基本面过滤
- 输出每个市场的优先品种和资金门槛

P2: 全品种扫描 + 自动换汇 + 整手预测 + 资金过滤
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from loguru import logger

from backend.config import DATA_DIR, trading_config
from configs.market_universe import StockEntry
from backend.data_engine.stock_universe import stock_universe


class MarketScanner:
    """全市场动态扫描器 — 验证品种、计算门槛、排序"""

    # 缓存有效期: 每 30 分钟刷新一次
    CACHE_TTL = 1800

    def __init__(self):
        self._cache_path = DATA_DIR / "scanned_universe.json"
        self._last_scan: float = 0
        self._scanned: List[Dict] = []
        self._by_market: Dict[str, List[Dict]] = {}
        self._affordable: List[Dict] = []
        self._total_available = 0

    # ── 主入口 ──
    def scan(
        self,
        tiger_client=None,
        available_cash: float = 0,
        positions: dict = None,
        force: bool = False,
    ) -> Dict:
        """
        扫描全市场可交易品种。

        Args:
            tiger_client: TigerClient 实例 (连接后传入)
            available_cash: 各币种可用现金 {currency: amount}
                e.g. {"USD": 2000, "HKD": 0, "SGD": 0}
            positions: 已有持仓 {ticker: shares} (用于优先级)
            force: 是否强制刷新缓存

        Returns:
            {
                "total_available": int,        # 总可交易品种数
                "by_market": {"US": [...], ...}, # 按市场分组
                "affordable": [...],            # 资金够买的品种(降序)
                "scan_time": float,             # Unix 时间戳
            }
        """
        now = time.time()
        if not force and self._scanned and (now - self._last_scan) < self.CACHE_TTL:
            self._recalc_affordable(available_cash)
            return self._summary()

        logger.info("🔍 全市场品种扫描中...")

        # 1. 加载全量候选池
        stock_universe.build(force=False)
        all_stocks: List[StockEntry] = stock_universe._all_stocks
        logger.info(f"  候选池: {len(all_stocks)} 只 (美股{len(stock_universe.us_tickers)} "
                   f"+ 港股{len(stock_universe.hk_tickers)} + 新加坡{len(stock_universe.sg_tickers)})")

        # 2. 如果 Tiger 在线，批量验证
        validated: List[Dict] = []
        if tiger_client and tiger_client.is_connected():
            validated = self._validate_with_tiger(tiger_client, all_stocks)
        else:
            # 离线模式 — 全部视为可交易
            validated = self._offline_validation(all_stocks)

        # 3. 按市场分组
        self._scanned = validated
        self._by_market = self._group_by_market(validated)
        self._total_available = len(validated)
        self._last_scan = time.time()

        # 4. 计算资金门槛
        self._calc_entry_barriers()
        self._recalc_affordable(available_cash)

        # 5. 缓存到 JSON
        self._save_cache()

        # 日志
        for mkt, stocks in self._by_market.items():
            logger.info(f"  {mkt}: {len(stocks)} 只可交易")

        return self._summary()

    # ── Tiger API 在线验证 ──
    def _validate_with_tiger(self, tiger_client, all_stocks: list) -> List[Dict]:
        """批量验证全量品种"""
        validated = []
        total = len(all_stocks)
        batch_size = 50  # Tiger API 限制

        for i in range(0, total, batch_size):
            batch = all_stocks[i:i + batch_size]
            tickers = [s.get("ticker", "") for s in batch if s.get("ticker")]
            if not tickers:
                continue

            try:
                # 批量获取实时报价 — 自动排除退市/停牌/价格无效的品种
                briefs = tiger_client._quote_client.get_stock_briefs(tickers)
                if briefs:
                    for j, brief in enumerate(briefs):
                        if j >= len(tickers):
                            break
                        ticker = tickers[j]
                        entry = batch[j]
                        price = getattr(brief, 'latest_price', 0) or 0

                        # 过滤条件
                        if price <= 0:
                            continue  # 价格无效 → 排除
                        if price < 0.10:
                            continue  # 仙股排除 (太便宜可能有退市风险)
                        if getattr(brief, 'status', None) == 'S':
                            continue  # 停牌排除

                        validated.append({
                            "ticker": ticker,
                            "name": entry.get("name", ticker),
                            "market": entry.get("market", "US"),
                            "currency": entry.get("currency", "USD"),
                            "sector": entry.get("sector", "Unknown"),
                            "price": float(price),
                            "lot_size": self._get_lot_size(ticker, entry.get("market", "US")),
                            "volume": getattr(brief, 'volume', 0) or 0,
                            "change_pct": getattr(brief, 'change', 0) or 0,
                            "benchmark_weight": entry.get("benchmark_weight", 0),
                            "affordable": False,  # 待资金计算
                            "min_capital_usd": 0,  # 待计算
                        })
            except Exception as e:
                logger.debug(f"  品种验证 batch {i//batch_size + 1} 失败: {e}")
                # 批次失败 → 该批次品种降级为离线验证
                for entry in batch:
                    validated.append(self._offline_entry(entry))

            time.sleep(0.1)  # API 限流保护

        return validated

    # ── 离线降级模式 ──
    def _offline_validation(self, all_stocks: list) -> List[Dict]:
        """无 Tiger 连接时的离线验证"""
        return [self._offline_entry(s) for s in all_stocks]

    def _offline_entry(self, entry: dict) -> Dict:
        """构建单个品种的离线条目"""
        ticker = entry.get("ticker", "")
        market = entry.get("market", "US")
        return {
            "ticker": ticker,
            "name": entry.get("name", ticker),
            "market": market,
            "currency": entry.get("currency", "USD"),
            "sector": entry.get("sector", "Unknown"),
            "price": 0,  # 0 表示未获取到实时价
            "lot_size": self._get_lot_size(ticker, market),
            "volume": 0,
            "change_pct": 0,
            "benchmark_weight": entry.get("benchmark_weight", 0),
            "affordable": True,  # 离线时全部视为可买
            "min_capital_usd": 0,
        }

    # ── 整手大小 ──
    @staticmethod
    def _get_lot_size(ticker: str, market: str) -> int:
        """获取最小交易单位"""
        if market == "US":
            return 1
        if market == "SG":
            return 100  # 新加坡默认100股

        # 港股 — 从已知列表 + 默认值
        from backend.data_engine.tiger_client import TigerClient
        return TigerClient.get_hk_lot_size(ticker)

    # ── 资金门槛计算 ──
    def _calc_entry_barriers(self):
        """计算每个品种的最低资金门槛(USD)"""
        for entry in self._scanned:
            price = entry["price"]
            lot = entry["lot_size"]
            currency = entry["currency"]
            fx_rate = trading_config.CURRENCY_RATES.get(currency, 1.0)

            if price > 0:
                # 买入1手所需本地货币
                local_cost = price * lot
                # 转换为 USD
                usd_cost = local_cost * fx_rate
                entry["min_capital_usd"] = round(usd_cost, 2)
            else:
                # 无实时价 — 用保守估算
                entry["min_capital_usd"] = 500 if currency == "USD" else 200

    # ── 资金过滤 ──
    def _recalc_affordable(self, available_cash: dict = None):
        """基于当前资金重新计算可买品种"""
        if not available_cash:
            available_cash = {}

        total_usd = sum(
            amount * trading_config.CURRENCY_RATES.get(ccy, 1.0)
            for ccy, amount in available_cash.items()
        )

        self._affordable = []
        for entry in self._scanned:
            min_capital = entry.get("min_capital_usd", 0)
            if total_usd <= 0:
                # 未提供现金数据 → 全部视为可买
                entry["affordable"] = True
                self._affordable.append(entry)
            elif min_capital > 0 and total_usd >= min_capital:
                entry["affordable"] = True
                self._affordable.append(entry)
            else:
                entry["affordable"] = False

        # 按 benchmark_weight 降序 → 优先蓝筹
        self._affordable.sort(
            key=lambda x: (x.get("benchmark_weight", 0), x.get("volume", 0)),
            reverse=True
        )

    # ── 分组 ──
    @staticmethod
    def _group_by_market(entries: List[Dict]) -> Dict[str, List[Dict]]:
        groups: Dict[str, List[Dict]] = {}
        for e in entries:
            mkt = e.get("market", "US")
            groups.setdefault(mkt, []).append(e)
        return groups

    # ── 摘要 ──
    def _summary(self) -> Dict:
        return {
            "total_available": self._total_available,
            "by_market": {
                mkt: len(stocks) for mkt, stocks in self._by_market.items()
            },
            "affordable_count": len(self._affordable),
            "affordable": self._affordable[:200],  # 返回前200只
            "scan_time": self._last_scan,
        }

    # ── 缓存 ──
    def _save_cache(self):
        try:
            with open(self._cache_path, "w", encoding="utf-8") as f:
                json.dump({
                    "scanned": self._scanned,
                    "last_scan": self._last_scan,
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug(f"缓存写入失败: {e}")

    def load_cache(self) -> bool:
        """从磁盘加载缓存"""
        if not self._cache_path.exists():
            return False
        try:
            with open(self._cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._scanned = data.get("scanned", [])
            self._last_scan = data.get("last_scan", 0)
            self._by_market = self._group_by_market(self._scanned)
            self._total_available = len(self._scanned)
            return True
        except Exception:
            return False

    # ── 查询 API ──
    def get_top_candidates(
        self,
        n: int = 50,
        include_positions: set = None,
        market_filter: str = None,
        min_price: float = 0,
        max_price: float = float('inf'),
        exclude_unaffordable: bool = True,
    ) -> List[str]:
        """
        获取最优候选股票列表。

        Args:
            n: 返回数量上限
            include_positions: 强制包含的持仓
            market_filter: 限定市场 (US/HK/SG)
            min_price/max_price: 价格区间
            exclude_unaffordable: 排除买不起的品种

        Returns:
            ticker 列表，按优先级排序
        """
        candidates = []
        pos_set = include_positions or set()

        # 优先持仓
        for entry in self._scanned:
            if entry["ticker"] in pos_set:
                candidates.append(entry)

        # 其他可交易品种
        for entry in self._affordable:
            if entry["ticker"] in pos_set:
                continue
            if market_filter and entry.get("market") != market_filter:
                continue
            price = entry.get("price", 0)
            if price < min_price or price > max_price:
                continue
            if exclude_unaffordable and not entry.get("affordable", True):
                continue
            candidates.append(entry)

        # 取 top N
        return [c["ticker"] for c in candidates[:n]]

    def get_affordable_tickers(self) -> List[str]:
        """获取当前资金可买的所有 ticker"""
        return [e["ticker"] for e in self._affordable]

    def get_market_distribution(self) -> Dict[str, int]:
        """各市场品种数量"""
        return {mkt: len(stocks) for mkt, stocks in self._by_market.items()}


# 全局单例
market_scanner = MarketScanner()
