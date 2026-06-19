"""
Lot Predictor + Capital Filter — 整手预测器 + 资金过滤

功能:
1. 提前查询/预测各市场最小交易单位 (lot size)
2. 计算买入所需最低资金 (本地货币 + USD 等值)
3. 资金不足的品种自动排除，不浪费 AI 推理时间
4. 港股整手覆盖范围扩展 (已知列表 + Tiger API 动态查询)

P2: 全品种扫描 + 自动换汇 + 整手预测 + 资金过滤
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from loguru import logger
from backend.config import trading_config


class LotPredictor:
    """整手预测 — 查询各个市场的最小交易单位"""

    # ═══════════════════════════════════════════
    # 港股整手对照表 (扩展版)
    # ═══════════════════════════════════════════
    HK_LOT_SIZES: Dict[str, int] = {
        # 大盘蓝筹 (成分股)
        "00005": 400,  "00011": 100,  "00016": 1000, "00027": 500,
        "00175": 100,  "00241": 500,  "00267": 1000, "00268": 200,
        "00270": 1000, "00288": 500,  "00291": 2000, "00316": 500,
        "00322": 200,  "00386": 2000, "00388": 100,  "00669": 100,
        "00688": 500,  "00700": 100,  "00762": 500,  "00823": 500,
        "00857": 2000, "00883": 1000, "00939": 1000, "00941": 500,
        "00981": 500,  "00992": 200,  "01024": 100,  "01038": 500,
        "01044": 500,  "01088": 500,  "01093": 200,  "01109": 500,
        "01171": 1000, "01177": 500,  "01193": 100,  "01209": 200,
        "01211": 100,  "01299": 100,  "01336": 100,  "01378": 1000,
        "01398": 1000, "01448": 1000, "01658": 200,  "01698": 100,
        "01772": 200,  "01776": 100,  "01787": 2000, "01797": 500,
        "01810": 200,  "01818": 500,  "01876": 200,  "01898": 1000,
        "01918": 1000, "01928": 200,  "01929": 200,  "01997": 100,
        "02007": 500,  "02013": 1000, "02015": 100,  "02018": 100,
        "02020": 500,  "02057": 100,  "02269": 100,  "02313": 100,
        "02318": 500,  "02319": 500,  "02328": 1000, "02333": 500,
        "02359": 100,  "02382": 100,  "02388": 500,  "02518": 200,
        "02601": 100,  "02618": 100,  "02628": 1000, "02688": 100,
        "02696": 100,  "02899": 2000, "03328": 1000, "03333": 1000,
        "03690": 100,  "03888": 200,  "03968": 500,  "03988": 1000,
        "03993": 2000, "06030": 100,  "06060": 100,  "06160": 100,
        "06862": 200,  "06969": 500,  "09618": 50,   "09626": 50,
        "09633": 100,  "09660": 100,  "09688": 20,   "09698": 50,
        "09866": 100,  "09888": 50,   "09896": 100,  "09899": 100,
        "09901": 100,  "09961": 50,   "09988": 100,  "09992": 100,
        "09999": 20,   "09997": 100,  "09995": 100,
    }

    # 默认整手大小
    DEFAULT_LOT = {
        "US": 1,
        "HK": 100,   # 港股默认 100 股
        "SG": 100,   # 新加坡默认 100 股
        "AU": 1,
        "NZ": 1,
    }

    def __init__(self):
        self._tiger_lot_cache: Dict[str, int] = {}
        self._last_tiger_query: float = 0

    # ── 主方法: 获取整手大小 ──
    def get_lot_size(
        self,
        ticker: str,
        market: str = "US",
        tiger_client=None,
    ) -> int:
        """
        获取股票最小交易单位。

        优先级:
        1. 已知对照表 (HK_LOT_SIZES)
        2. Tiger API 动态查询
        3. 默认值 (按市场)

        Args:
            ticker: 如 '00700', 'AAPL', 'D05.SI'
            market: US/HK/SG/AU/NZ
            tiger_client: TigerClient 实例

        Returns:
            最小交易股数
        """
        # 美股/AU/NZ → 1股
        if market in ("US", "AU", "NZ"):
            return 1

        # 新加坡 → 默认100股
        if market == "SG":
            return 100

        # 港股 — 清理 ticker 前缀
        clean = ticker.replace(".HK", "").replace(".hk", "")

        # 1. 已知列表
        if clean in self.HK_LOT_SIZES:
            return self.HK_LOT_SIZES[clean]

        # 2. Tiger API 动态查询
        if tiger_client and tiger_client.is_connected():
            lot = self._query_tiger_lot(clean, tiger_client)
            if lot > 0:
                self._tiger_lot_cache[clean] = lot
                return lot

        # 3. 默认
        return self.DEFAULT_LOT.get(market, 100)

    def _query_tiger_lot(self, symbol: str, tiger_client) -> int:
        """通过 Tiger API 查询合约信息获取整手大小"""
        import time
        now = time.time()

        # 缓存 (30分钟)
        if symbol in self._tiger_lot_cache and (now - self._last_tiger_query) < 1800:
            return self._tiger_lot_cache[symbol]

        try:
            # 尝试通过 contract 查询
            from tigeropen.common.contract import Contract
            from tigeropen.common.util.contract_utils import stock_contract

            contract = stock_contract(symbol, "HK")
            if contract and hasattr(contract, 'lot_size'):
                self._last_tiger_query = now
                return contract.lot_size
        except Exception:
            pass

        return 0  # 查询失败

    # ── 资金门槛计算 ──
    def calc_min_capital(
        self,
        ticker: str,
        price: float,
        market: str = "US",
        tiger_client=None,
    ) -> Dict:
        """
        计算买入一只股票的最低资金需求。

        Args:
            ticker: 股票代码
            price: 当前价格 (本地货币)
            market: 市场代码
            tiger_client: Tiger 客户端

        Returns:
            {
                "ticker": str,
                "lot_size": int,         # 最小交易单位
                "price_local": float,    # 单价(本地货币)
                "min_local": float,      # 最低买入成本(本地货币)
                "min_usd": float,        # 最低买入成本(USD)
                "affordable": bool,      # 是否买得起
                "currency": str,         # 币种
            }
        """
        lot_size = self.get_lot_size(ticker, market, tiger_client)
        currency = self._get_currency(ticker, market)
        fx_rate = trading_config.CURRENCY_RATES.get(currency, 1.0)

        min_local = price * lot_size
        # 加佣金缓冲 0.5%
        min_local *= 1.005
        min_usd = min_local * fx_rate

        return {
            "ticker": ticker,
            "lot_size": lot_size,
            "price_local": round(price, 4),
            "min_local": round(min_local, 2),
            "min_usd": round(min_usd, 2),
            "affordable": False,  # 调用方填充
            "currency": currency,
        }

    @staticmethod
    def _get_currency(ticker: str, market: str) -> str:
        """根据 ticker 和市场确定币种"""
        ticker_upper = ticker.upper()
        if ".HK" in ticker_upper or market == "HK":
            return "HKD"
        elif ".SI" in ticker_upper or market == "SG":
            return "SGD"
        elif ".AX" in ticker_upper or market == "AU":
            return "AUD"
        elif ".NZ" in ticker_upper or market == "NZ":
            return "NZD"
        return "USD"

    # ── 批量资金过滤 ──
    def filter_affordable(
        self,
        tickers: List[str],
        prices: Dict[str, float],
        available_cash_usd: float,
        markets: Dict[str, str] = None,
        tiger_client=None,
    ) -> Tuple[List[str], Dict, List[str]]:
        """
        批量过滤 — 排除资金不足的品种。

        Args:
            tickers: 候选 ticker 列表
            prices: {ticker: price_local}
            available_cash_usd: 各币种可用现金 (USD 等价总和)
            markets: {ticker: market} 市场映射
            tiger_client: Tiger 客户端

        Returns:
            (affordable_tickers, capital_detail, excluded_tickers)
        """
        if markets is None:
            markets = {}

        affordable = []
        excluded = []
        capital_detail = {}

        for ticker in tickers:
            price = prices.get(ticker, 0)
            if price <= 0:
                excluded.append(ticker)
                continue

            market = markets.get(ticker, "US")
            detail = self.calc_min_capital(ticker, price, market, tiger_client)

            # 同币种现金判断
            currency = detail["currency"]
            rate = trading_config.CURRENCY_RATES.get(currency, 1.0)
            cash_in_ccy = available_cash_usd / rate if rate > 0 else 0

            if cash_in_ccy >= detail["min_local"]:
                detail["affordable"] = True
                affordable.append(ticker)
            else:
                detail["affordable"] = False
                excluded.append(ticker)
                logger.debug(f"  🚫 {ticker}: 需 {currency} {detail['min_local']:.0f}, "
                           f"仅 {currency} {cash_in_ccy:.0f}")

            capital_detail[ticker] = detail

        if excluded:
            logger.info(f"💰 资金过滤: {len(affordable)} 只可买, {len(excluded)} 只钱不够排除")

        return affordable, capital_detail, excluded

    # ── AI 推理前预过滤 ──
    def pre_filter_for_ai(
        self,
        universe: List[Dict],
        available_cash_usd: float,
        n_top: int = 100,
    ) -> List[str]:
        """
        AI 推理前预过滤 — 只保留买得起的 Top-N 品种。

        减少 AI 推理开销，跳过注定无法交易的品种。

        Args:
            universe: 全量扫描结果 (market_scanner 的 affordable 列表)
            available_cash_usd: 可用现金 USD 等值
            n_top: 最多返回数

        Returns:
            过滤后的 ticker 列表 (按 priority 排序)
        """
        candidates = []

        for entry in universe:
            min_cap = entry.get("min_capital_usd", 0)
            if min_cap <= 0:
                # 无价格信息 → 保留
                candidates.append(entry)
            elif available_cash_usd >= min_cap:
                # 买得起
                candidates.append(entry)
            else:
                # 买不起 → 跳过
                pass

        # 排序: benchmark_weight 降序
        candidates.sort(
            key=lambda x: (x.get("benchmark_weight", 0), x.get("volume", 0)),
            reverse=True
        )

        logger.info(f"🧹 AI预过滤: {len(universe)} → {len(candidates[:n_top])} 只 "
                   f"(资金≥${available_cash_usd:,.0f})")

        return [c["ticker"] for c in candidates[:n_top]]

    # ── 港股整手覆盖统计 ──
    def get_hk_lot_coverage(self, tickers: List[str]) -> Dict:
        """统计港股整手覆盖情况"""
        total = 0
        known = 0
        unknown = 0

        for t in tickers:
            if ".HK" not in t.upper():
                continue
            clean = t.replace(".HK", "").replace(".hk", "")
            total += 1
            if clean in self.HK_LOT_SIZES:
                known += 1
            else:
                unknown += 1

        return {
            "total_hk": total,
            "known_lot": known,
            "unknown_lot": unknown,
            "coverage": round(known / max(total, 1) * 100, 1),
        }


# 全局单例
lot_predictor = LotPredictor()
