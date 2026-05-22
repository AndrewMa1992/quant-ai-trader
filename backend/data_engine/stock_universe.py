"""
全市场股票扫描器 - Stock Universe Manager
- 自动获取美股（S&P500 + Nasdaq100）+ 港股（恒生 + 国企）成分股
- 按市值 / 成交量 / 波动率筛选
- 维护本地股票池，支持增量更新
- 为 AI 分析提供候选标的
"""
import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Set
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import yfinance as yf
from loguru import logger

PROJ_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJ_ROOT / "backend" / "data"
UNIVERSE_FILE = DATA_DIR / "stock_universe.json"


class StockUniverse:
    """
    全市场股票池管理器

    数据来源:
    - US: Wikipedia S&P 500 + Nasdaq 100 列表
    - HK: 预置恒生指数 + 国企指数成分股

    筛选条件（可配置）:
    - 市值 > $500M
    - 日均成交量 > 200K
    - 排除仙股（价格 < $1）
    """

    def __init__(self):
        self._us_stocks: List[Dict] = []
        self._hk_stocks: List[Dict] = []
        self._all_stocks: List[Dict] = []
        self._last_update: Optional[datetime] = None
        self._load_cache()

    # ================================================================
    # 股票池获取
    # ================================================================

    def fetch_us_universe(self, max_stocks: int = 500) -> List[str]:
        """获取美股池（S&P500 + Nasdaq100 去重）"""
        tickers: Set[str] = set()

        try:
            # S&P 500
            sp500 = pd.read_html(
                "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
            )[0]
            for t in sp500["Symbol"].tolist():
                tickers.add(str(t).replace(".", "-"))
            logger.info(f"📊 S&P 500: {len(tickers)} 只")
        except Exception as e:
            logger.warning(f"⚠️ S&P 500 获取失败: {e}，使用缓存")

        try:
            # Nasdaq 100
            nasdaq = pd.read_html(
                "https://en.wikipedia.org/wiki/Nasdaq-100"
            )[4]  # 第5个表
            for t in nasdaq["Ticker"].tolist():
                tickers.add(str(t).replace(".", "-"))
            logger.info(f"📊 +Nasdaq 100: {len(tickers)} 只 (含S&P500)")
        except Exception as e:
            logger.warning(f"⚠️ Nasdaq 100 获取失败: {e}")

        # 兜底：预置核心美股（覆盖主要行业）
        if len(tickers) < 50:
            tickers = {
                # 科技
                "AAPL","MSFT","GOOGL","AMZN","NVDA","META","TSLA","NFLX","ADBE","CRM",
                "CSCO","INTC","AMD","QCOM","TXN","AVGO","ORCL","IBM","NOW","SNOW",
                "MU","AMAT","LRCX","ADI","UBER","PYPL","SQ","SHOP","ZM","DDOG",
                "CRWD","NET","PLTR","SNPS","CDNS","WDAY","TEAM","INTU","ADSK","FTNT",
                # 金融
                "JPM","V","MA","BAC","WFC","GS","MS","AXP","BLK","SCHW",
                "C","USB","PNC","COF","BK","TFC","AIG","MET","PRU","ICE",
                # 医疗
                "UNH","JNJ","PFE","MRK","ABT","TMO","DHR","LLY","ABBV","BMY",
                "AMGN","GILD","ISRG","REGN","VRTX","CI","HUM","ZTS","BDX","BSX",
                # 消费
                "WMT","PG","COST","KO","PEP","HD","NKE","MCD","SBUX","DIS",
                "LOW","TGT","TJX","ROST","DG","DLTR","ULTA","LULU","CMG","YUM",
                # 工业/能源
                "XOM","CVX","CAT","DE","BA","GE","HON","LMT","UPS","RTX",
                "UNP","NSC","FDX","DAL","LUV","COP","EOG","SLB","PSX","VLO",
                # ETF
                "SPY","QQQ","IWM","DIA","XLF","XLE","XLK","XLV","XLI","XLY",
                # 中概/半导体
                "BABA","TSM","ASML","SAP",
            }
            logger.warning(f"⚠️ 使用预置美股池: {len(tickers)} 只")

        return list(tickers)[:max_stocks]

    def fetch_hk_universe(self) -> List[str]:
        """获取港股池（恒生指数 + 国企指数成分股）"""
        # 恒生指数 + 国企指数成分股（2025年最新）
        hk_stocks = [
            # 恒生指数成分股
            "00700", "09988", "03690", "09999", "01810", "00941",
            "00883", "01299", "02318", "02628", "03988", "01398",
            "00005", "00011", "00016", "00027", "00066", "00101",
            "00175", "00241", "00267", "00288", "00316", "00386",
            "00669", "00823", "01038", "01093", "01109", "01113",
            "01211", "01876", "01929", "02015", "02020", "02269",
            "02313", "02319", "02331", "02382", "02388", "02688",
            "02899", "03692", "03888", "06160", "06618", "09618",
            "09633", "09688", "09888", "09901", "09961", "09992",
            # 国企指数
            "00728", "01088", "02601", "03968", "06030", "06881",
            # 热门港股
            "09866", "09868", "02013", "01833", "06098", "00136",
        ]
        logger.info(f"📊 港股池: {len(hk_stocks)} 只")
        return hk_stocks

    # ================================================================
    # 筛选逻辑
    # ================================================================

    def screen_stocks(
        self,
        tickers: List[str],
        min_market_cap: float = 500_000_000,   # $500M
        min_avg_volume: int = 200_000,         # 200K shares/day
        min_price: float = 1.0,                # > $1
        max_workers: int = 20,
    ) -> List[Dict]:
        """
        对股票列表进行并行筛选
        返回: [{ticker, name, market_cap, avg_volume, price, volatility, sector}, ...]
        """
        results = []
        total = len(tickers)

        logger.info(f"🔍 筛选 {total} 只股票...")

        def _screen_one(ticker: str) -> Optional[Dict]:
            try:
                stock = yf.Ticker(ticker)
                info = stock.info

                cap = info.get("marketCap", 0) or 0
                vol = info.get("averageVolume", 0) or 0
                price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
                name = info.get("shortName") or info.get("longName") or ticker
                sector = info.get("sector", "")
                beta = info.get("beta", 1.0)

                if cap < min_market_cap:
                    return None
                if vol < min_avg_volume:
                    return None
                if price < min_price:
                    return None

                # 获取短期波动率
                try:
                    hist = stock.history(period="1mo")
                    if len(hist) >= 10:
                        returns = hist["Close"].pct_change().dropna()
                        volatility = float(returns.std() * np.sqrt(252))
                    else:
                        volatility = 0.3
                except Exception:
                    volatility = 0.3

                return {
                    "ticker": ticker,
                    "name": name,
                    "market_cap": cap,
                    "avg_volume": vol,
                    "price": price,
                    "volatility": volatility,
                    "beta": beta,
                    "sector": sector,
                }
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_screen_one, t): t for t in tickers}
            for i, f in enumerate(as_completed(futures)):
                try:
                    r = f.result(timeout=15)
                    if r:
                        results.append(r)
                except Exception:
                    pass
                if (i + 1) % 100 == 0:
                    logger.info(f"   进度 {i+1}/{total}, 通过 {len(results)}")
                elif (i + 1) % 500 == 0:
                    logger.info(f"   进度 {i+1}/{total}, 通过 {len(results)}")

        logger.info(f"✅ 筛选完成: {len(results)}/{total} 通过")
        return results

    def quick_screen(
        self,
        tickers: List[str],
        max_workers: int = 30,
    ) -> List[str]:
        """
        快速筛选（仅用基本信息，不回测波动率）
        适合日常更新
        """
        results = []

        def _quick(ticker: str) -> Optional[str]:
            try:
                stock = yf.Ticker(ticker)
                info = stock.info
                cap = info.get("marketCap", 0) or 0
                price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
                if cap >= 200_000_000 and price >= 0.50:
                    return ticker
            except Exception:
                pass
            return None

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_quick, t) for t in tickers]
            for f in as_completed(futures):
                try:
                    r = f.result(timeout=10)
                    if r:
                        results.append(r)
                except Exception:
                    pass

        logger.info(f"⚡ 快速筛选: {len(results)}/{len(tickers)}")
        return results

    # ================================================================
    # 缓存管理
    # ================================================================

    def build(self, force: bool = False):
        """构建/更新全市场股票池"""
        # 检查缓存
        if not force and self._last_update:
            age = (datetime.now() - self._last_update).total_seconds()
            if age < 86400:  # 24小时内
                logger.info(f"📦 使用缓存 ({len(self._all_stocks)} 只, {age/3600:.1f}h 前更新)")
                return

        logger.info("🏗️ 构建全市场股票池...")

        # 1. 获取成分股
        us_raw = self.fetch_us_universe()
        hk_raw = self.fetch_hk_universe()

        # 2. 筛选（首次全量，后续增量）
        if not self._all_stocks or force:
            us_screened = self.screen_stocks(us_raw, max_workers=25)
            # HK 用 yfinance 不可靠，直接从列表通过（market_data 用 tiger_open）
            hk_screened = [{"ticker": t, "name": t, "market_cap": 1e10, "avg_volume": 1e6, 
                           "price": 50, "volatility": 0.3, "beta": 1.0, "sector": "HK"}
                          for t in hk_raw]
        else:
            us_screened = self.quick_screen(us_raw)
            hk_screened = [{"ticker": t, "name": t, "market_cap": 1e10, "avg_volume": 1e6,
                           "price": 50, "volatility": 0.3, "beta": 1.0, "sector": "HK"}
                          for t in hk_raw]

        # 3. 组装
        self._us_stocks = us_screened
        self._hk_stocks = hk_screened
        self._all_stocks = us_screened + hk_screened
        self._last_update = datetime.now()

        self._save_cache()

        logger.info(f"✅ 股票池构建完成: US {len(self._us_stocks)} + HK {len(self._hk_stocks)} = {len(self._all_stocks)} 只")

    def _save_cache(self):
        data = {
            "last_update": self._last_update.isoformat() if self._last_update else None,
            "us_count": len(self._us_stocks),
            "hk_count": len(self._hk_stocks),
            "stocks": [s for s in self._all_stocks if isinstance(s, dict)],
        }
        with open(UNIVERSE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    def _load_cache(self):
        if UNIVERSE_FILE.exists():
            try:
                with open(UNIVERSE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._all_stocks = data.get("stocks", [])
                self._us_stocks = [s for s in self._all_stocks if not s.get("ticker","").endswith(".HK")]
                self._hk_stocks = [s for s in self._all_stocks if s.get("ticker","").endswith(".HK")]
                if data.get("last_update"):
                    self._last_update = datetime.fromisoformat(data["last_update"])
                logger.info(f"📦 加载缓存: {len(self._all_stocks)} 只 ({data.get('us_count',0)} US + {data.get('hk_count',0)} HK)")
            except Exception as e:
                logger.warning(f"⚠️ 缓存加载失败: {e}")

    # ================================================================
    # 获取方法
    # ================================================================

    @property
    def us_tickers(self) -> List[str]:
        return [s["ticker"] if isinstance(s, dict) else s for s in self._us_stocks]

    @property
    def hk_tickers(self) -> List[str]:
        raw = [s["ticker"] if isinstance(s, dict) else s for s in self._hk_stocks]
        # 转 5 位补零格式用于 yfinance
        return [t.zfill(5) if t.isdigit() else t for t in raw]

    @property
    def all_tickers(self) -> List[str]:
        """所有 ticker，HK 加 .HK 后缀"""
        us = self.us_tickers
        hk = [f"{t}.HK" for t in self.hk_tickers]
        return us + hk

    def get_top_by(self, key: str = "market_cap", n: int = 50) -> List[Dict]:
        """按指标排序取 top N"""
        dict_stocks = [s for s in self._all_stocks if isinstance(s, dict)]
        sorted_stocks = sorted(dict_stocks, key=lambda x: x.get(key, 0) or 0, reverse=True)
        return sorted_stocks[:n]

    def get_high_volatility(self, n: int = 50) -> List[Dict]:
        """高波动率股票（交易机会多）"""
        dict_stocks = [s for s in self._all_stocks if isinstance(s, dict)]
        sorted_stocks = sorted(dict_stocks, key=lambda x: x.get("volatility", 0) or 0, reverse=True)
        return sorted_stocks[:n]

    def summary(self) -> Dict:
        """股票池摘要"""
        return {
            "us_count": len(self._us_stocks),
            "hk_count": len(self._hk_stocks),
            "total": len(self._all_stocks),
            "last_update": self._last_update.isoformat() if self._last_update else None,
            "top_mcap": self.get_top_by("market_cap", 10),
            "top_volatile": self.get_high_volatility(10),
        }


# 全局单例
stock_universe = StockUniverse()


if __name__ == "__main__":
    print("🏗️ 构建全市场股票池...")
    stock_universe.build(force=True)
    s = stock_universe.summary()
    print(f"\n📊 股票池概览:")
    print(f"   US: {s['us_count']} 只")
    print(f"   HK: {s['hk_count']} 只")
    print(f"   总计: {s['total']} 只")
    print(f"\n📈 Top 10 市值:")
    for st in s["top_mcap"][:10]:
        cap_b = st.get("market_cap", 0) / 1e9 if st.get("market_cap") else 0
        print(f"   {st['ticker']:10s} {st.get('name',''):30s} ${cap_b:.1f}B")
