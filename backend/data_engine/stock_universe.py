"""
Cross-market stock scanner - Stock Universe Manager.
- Auto-fetch US (S&P 500 + Nasdaq 100) + HK (Hang Seng + H-share) constituents
- Screen by market cap / volume / volatility
- Maintain a local universe with incremental updates
- Supply candidate names for AI analysis
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
from loguru import logger

PROJ_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJ_ROOT / "backend" / "data"
UNIVERSE_FILE = DATA_DIR / "stock_universe.json"


class StockUniverse:
    """
    Cross-market stock-universe manager.

    Data sources:
    - US: Wikipedia S&P 500 + Nasdaq 100 lists
    - HK: preset Hang Seng Index + H-share Index constituents
    - SG: preset Straits Times Index (STI) constituents
    - AU: Wikipedia S&P/ASX 200 list
    - NZ: preset NZX 50 constituents

    Screening (configurable):
    - Market cap > $500M
    - Average daily volume > 200K
    - Exclude penny stocks (price < $1)
    """

    def __init__(self):
        self._us_stocks: List[Dict] = []
        self._hk_stocks: List[Dict] = []
        self._sg_stocks: List[Dict] = []
        self._au_stocks: List[Dict] = []
        self._nz_stocks: List[Dict] = []
        self._cn_stocks: List[Dict] = []
        self._all_stocks: List[Dict] = []
        self._last_update: Optional[datetime] = None
        self._load_cache()

    # ================================================================
    # Universe fetch
    # ================================================================

    def fetch_us_universe(self, max_stocks: int = 1200) -> List[str]:
        """Fetch the US universe (S&P500 + Nasdaq100 + Russell 1000, de-duplicated)."""
        tickers: Set[str] = set()

        try:
            # S&P 500
            sp500 = pd.read_html(
                "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
            )[0]
            for t in sp500["Symbol"].tolist():
                tickers.add(str(t).replace(".", "-"))
            logger.info(f"📊 S&P 500: {len(tickers)} names")
        except Exception as e:
            logger.warning(f"⚠️ S&P 500 fetch failed: {e}")

        try:
            # Nasdaq 100
            nasdaq = pd.read_html(
                "https://en.wikipedia.org/wiki/Nasdaq-100"
            )[4]
            for t in nasdaq["Ticker"].tolist():
                tickers.add(str(t).replace(".", "-"))
            logger.info(f"📊 +Nasdaq 100: {len(tickers)} names")
        except Exception as e:
            logger.warning(f"⚠️ Nasdaq 100 fetch failed: {e}")

        try:
            # Russell 1000
            russell = pd.read_html(
                "https://en.wikipedia.org/wiki/Russell_1000_Index"
            )[2]  # the 3rd table is typically the constituents
            if "Ticker" in russell.columns:
                for t in russell["Ticker"].tolist():
                    tickers.add(str(t).replace(".", "-"))
            logger.info(f"📊 +Russell 1000: {len(tickers)} names")
        except Exception as e:
            logger.warning(f"⚠️ Russell 1000 fetch failed: {e}; using extended preset list")

        # Extended preset (covers common Russell 1000 names + China ADRs + ETFs)
        if len(tickers) < 200:
            tickers = {
                # Tech (40)
                "AAPL","MSFT","GOOGL","AMZN","NVDA","META","TSLA","NFLX","ADBE","CRM",
                "CSCO","INTC","AMD","QCOM","TXN","AVGO","ORCL","IBM","NOW","SNOW",
                "MU","AMAT","LRCX","ADI","UBER","PYPL","SQ","SHOP","ZM","DDOG",
                "CRWD","NET","PLTR","SNPS","CDNS","WDAY","TEAM","INTU","ADSK","FTNT",
                # Tech extension (20)
                "PANW","ZS","OKTA","MDB","DOCU","COUP","TWLO","RNG","SPLK","AKAM",
                "ANET","DELL","HPQ","HPE","STX","WDC","NTAP","MRVL","KLAC","TER",
                # Financials (25)
                "JPM","V","MA","BAC","WFC","GS","MS","AXP","BLK","SCHW",
                "C","USB","PNC","COF","BK","TFC","AIG","MET","PRU","ICE",
                "CME","CB","TRV","AFL","BX",
                # Healthcare (25)
                "UNH","JNJ","PFE","MRK","ABT","TMO","DHR","LLY","ABBV","BMY",
                "AMGN","GILD","ISRG","REGN","VRTX","CI","HUM","ZTS","BDX","BSX",
                "CVS","ANTM","HCA","MCK","EW",
                # Consumer (25)
                "WMT","PG","COST","KO","PEP","HD","NKE","MCD","SBUX","DIS",
                "LOW","TGT","TJX","ROST","DG","DLTR","ULTA","LULU","CMG","YUM",
                "EL","CL","KMB","MDLZ","MNST",
                # Industrials / energy (25)
                "XOM","CVX","CAT","DE","BA","GE","HON","LMT","UPS","RTX",
                "UNP","NSC","FDX","DAL","LUV","COP","EOG","SLB","PSX","VLO",
                "MMM","EMR","ETN","ITW","ROK",
                # REITs / telecom (15)
                "AMT","PLD","CCI","EQIX","SPG","O","VZ","T","TMUS","CHTR",
                "CMCSA","SBAC","WELL","AVB","DLR",
                # ETF (10)
                "SPY","QQQ","IWM","DIA","XLF","XLE","XLK","XLV","XLI","XLY",
                # China ADRs / international (15)
                "BABA","JD","PDD","BIDU","NIO","LI","XPEV","BILI","TME",
                "TSM","ASML","SAP","SONY","TM","BP",
            }
            logger.warning(f"⚠️ Using extended preset US universe: {len(tickers)} names")

        return list(tickers)[:max_stocks]

    def fetch_hk_universe(self) -> List[str]:
        """Fetch the HK universe (Hang Seng Composite + H-shares + popular HK names ~250)."""
        hk_stocks = [
            # === Hang Seng Index constituents (82) ===
            "00005","00011","00012","00016","00017","00019","00027","00066",
            "00101","00175","00241","00267","00268","00285","00288","00291",
            "00316","00322","00386","00388","00669","00688","00700","00762",
            "00823","00857","00868","00881","00883","00939","00941","00960",
            "00968","00981","00992","01038","01044","01088","01093","01109",
            "01113","01177","01209","01211","01288","01299","01378","01398",
            "01810","01876","01928","01929","01997","02007","02015","02018",
            "02020","02269","02313","02318","02319","02328","02331","02382",
            "02388","02601","02628","02688","02899","03690","03888","03968",
            "03988","06030","06160","06618","06862","09618","09633","09688",
            "09888","09901","09961","09988","09992","09999",
            # === Extra H-share Index names (20) ===
            "00728","01099","01171","01818","02039","02202","02618","03328",
            "03898","06098","06881","00136","00270","00392","01193","02696",
            # === Biotech (15) ===
            "02269","01801","06160","06855","02162","01548","02500","02196",
            "09926","02157","06990","06618","02096","02170","09966",
            # === Tech / internet (20) ===
            "02013","01833","01797","09923","01024","09899","09866","09868",
            "02423","06690","01347","00780","09990","03888","00777",
            "09626","09878","02518","09998","01020",
            # === Consumer / retail (15) ===
            "00291","00168","02219","06808","02331","02020","06110",
            "01368","01773","01579","06837","09922","09987","09896",
            # === New energy / auto (10) ===
            "01211","02015","09863","09868","02238","00175","00425",
            "01772","09696","09866",
            # === Mainland financials (10) ===
            "01339","02611","06066","06881","06886","06099","06178",
            "03908","06030","01776",
        ]
        # De-duplicate
        hk_stocks = list(dict.fromkeys(hk_stocks))
        logger.info(f"📊 HK universe: {len(hk_stocks)} names")
        return hk_stocks

    def fetch_sg_universe(self) -> List[str]:
        """Fetch the Singapore universe (STI + mid/large caps ~100)."""
        sg_stocks = [
            # STI 30 constituents
            "D05.SI","O39.SI","U11.SI","Z74.SI","C52.SI","C6L.SI",
            "S58.SI","BS6.SI","U96.SI","C09.SI","F34.SI","U14.SI",
            "S68.SI","V03.SI","BN4.SI","T39.SI","G13.SI","H78.SI",
            "Y92.SI","C07.SI","C31.SI","S51.SI","N2IU.SI","J36.SI",
            "M44U.SI","A17U.SI","AU8U.SI","C38U.SI",
            # REITs (20)
            "C2PU.SI","C61U.SI","J69U.SI","K71U.SI","M1GU.SI",
            "N2IU.SI","SK6U.SI","T82U.SI","ACV.SI","BWCU.SI",
            "BUOU.SI","CRPU.SI","DCRU.SI","EDMU.SI","K2LU.SI",
            "ME8U.SI","ND8U.SI","OXMU.SI","RW0U.SI","UD1U.SI",
            # Financials (10)
            "D01.SI","G07.SI","O10.SI","T14.SI","U06.SI",
            "A26.SI","F01.SI","P15.SI","S23.SI","S59.SI",
            # Industrials / consumer / tech (40)
            "S63.SI","C70.SI","G18.SI","H02.SI","I07.SI",
            "J85.SI","K17.SI","L19.SI","M01.SI","N03.SI",
            "R01.SI","S08.SI","S10.SI","T12.SI","U04.SI",
            "V01.SI","W05.SI","Y03.SI","Z01.SI","A04.SI",
            "B02.SI","B69.SI","BVA.SI","C04.SI","C76.SI",
            "D03.SI","E02.SI","F03.SI","F83.SI","G92.SI",
            "H13.SI","H22.SI","I49.SI","J03.SI","K01.SI",
            "L02.SI","M05.SI","N01.SI","O01.SI","P01.SI",
        ]
        sg_stocks = list(dict.fromkeys(sg_stocks))
        logger.info(f"📊 Singapore universe: {len(sg_stocks)} names")
        return sg_stocks

    def fetch_au_universe(self) -> List[str]:
        """Fetch the Australia universe (S&P/ASX 200 constituents)."""
        tickers: Set[str] = set()

        try:
            asx200 = pd.read_html(
                "https://en.wikipedia.org/wiki/S%26P/ASX_200"
            )[0]
            if "Code" in asx200.columns:
                for t in asx200["Code"].tolist():
                    tickers.add(f"{str(t).strip()}.AX")
            elif "Ticker" in asx200.columns:
                for t in asx200["Ticker"].tolist():
                    tickers.add(f"{str(t).strip()}.AX")
            logger.info(f"📊 ASX 200: {len(tickers)} names")
        except Exception as e:
            logger.warning(f"⚠️ ASX 200 fetch failed: {e}")

        # Fallback
        if len(tickers) < 20:
            tickers = {
                "BHP.AX","CBA.AX","CSL.AX","NAB.AX","WBC.AX",
                "ANZ.AX","MQG.AX","WES.AX","WOW.AX","TLS.AX",
                "WDS.AX","FMG.AX","RIO.AX","GMG.AX","ALL.AX",
                "COL.AX","QBE.AX","SUN.AX","ORG.AX","STO.AX",
                "NCM.AX","RHC.AX","SHL.AX","CPU.AX","XRO.AX",
                "REA.AX","SEK.AX","CAR.AX","TCL.AX","SCG.AX",
            }
            logger.warning(f"⚠️ Using preset AU universe: {len(tickers)} names")

        return list(tickers)

    def fetch_nz_universe(self) -> List[str]:
        """Fetch the New Zealand universe (NZX 50 constituents)."""
        nz_stocks = [
            # NZX 50 constituents (yfinance .NZ suffix)
            "FPH.NZ", "AIA.NZ", "MEL.NZ", "SPK.NZ",
            "ATM.NZ", "MCY.NZ", "IFT.NZ", "EBO.NZ",
            "SUM.NZ", "RYM.NZ", "CEN.NZ", "MEL.NZ",
            "CNU.NZ", "FBU.NZ", "GMT.NZ", "KPG.NZ",
            "PCT.NZ", "POT.NZ", "SKC.NZ", "SKT.NZ",
            "STU.NZ", "THL.NZ", "VHP.NZ", "VGL.NZ",
            "OCA.NZ", "ARG.NZ", "ARV.NZ", "GNE.NZ",
            "MCY.NZ", "ZEL.NZ",
        ]
        logger.info(f"📊 New Zealand universe: {len(nz_stocks)} names")
        return nz_stocks

    def _fetch_cn_stocks(self) -> List[str]:
        """Fetch the A-share universe (CSI 300 core + ChiNext leaders).

        Dynamically fetched via AkShare / efinance; falls back to a hardcoded preset.
        Ticker format: 600000.SH (SSE), 000001.SZ (SZSE)
        """
        tickers: List[str] = []
        try:
            import efinance as ef
            # Try CSI 300 constituents via efinance
            df = ef.stock.get_realtime_quotes()
            if df is not None and not df.empty:
                # efinance column "stock code" is returned in Chinese; keep the API key
                code_col = "\u80a1\u7968\u4ee3\u7801"
                if code_col not in df.columns:
                    code_col = next(
                        (c for c in df.columns if "code" in str(c).lower() or c == code_col),
                        df.columns[0],
                    )
                tickers = [
                    f"{code}.{'SH' if code.startswith('6') else 'SZ'}"
                    for code in df[code_col].astype(str).head(300)
                ]
                logger.info(f"📊 efinance A-shares: {len(tickers)} names")
        except Exception:
            pass

        if len(tickers) < 50:
            # Preset: CSI 300 core + ChiNext leaders (ticker.SH / ticker.SZ)
            tickers = [
                # SSE 50 core
                "600519.SH", "601318.SH", "600036.SH", "601398.SH",
                "600900.SH", "601166.SH", "600276.SH", "601012.SH",
                "600030.SH", "601888.SH", "600887.SH", "600809.SH",
                "600585.SH", "600690.SH", "601899.SH", "600048.SH",
                "601088.SH", "600104.SH", "601668.SH", "600028.SH",
                # SZSE / ChiNext core
                "000858.SZ", "000333.SZ", "002594.SZ", "300750.SZ",
                "000651.SZ", "002415.SZ", "000568.SZ", "300059.SZ",
                "002475.SZ", "000001.SZ", "000002.SZ", "002230.SZ",
                "000725.SZ", "002142.SZ", "300124.SZ", "000063.SZ",
                "002714.SZ", "000776.SZ", "300015.SZ", "002352.SZ",
            ]
            logger.info(f"📊 Preset A-share universe: {len(tickers)} names")
        return tickers

    # ================================================================
    # Screening
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
        Screen a ticker list in parallel.
        Returns: [{ticker, name, market_cap, avg_volume, price, volatility, sector}, ...]
        """
        results = []
        total = len(tickers)

        logger.info(f"🔍 Screening {total} stocks...")

        def _screen_one(ticker: str) -> Optional[Dict]:
            try:
                from backend.data_engine.china_adapter import china_data_adapter
                quote = china_data_adapter.get_realtime_quote(ticker)
                if not quote or not quote.get("price"):
                    return None

                price = quote["price"]
                name = quote.get("name", ticker)

                # Simplified screen: when market_cap is missing, use price + name
                if price < min_price:
                    return None

                # Short-horizon volatility
                volatility = 0.3
                try:
                    df = china_data_adapter.get_historical_data(ticker, period="1mo", interval="1d")
                    if len(df) >= 10 and "close" in df.columns:
                        returns = df["close"].pct_change().dropna()
                        volatility = float(returns.std() * np.sqrt(252))
                except Exception:
                    pass

                return {
                    "ticker": ticker,
                    "name": name,
                    "market_cap": 0,  # China APIs do not provide this field
                    "avg_volume": quote.get("volume", 0),
                    "price": price,
                    "volatility": volatility,
                    "beta": 1.0,
                    "sector": "",
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
                    logger.info(f"   Progress {i+1}/{total}, passed {len(results)}")
                elif (i + 1) % 500 == 0:
                    logger.info(f"   Progress {i+1}/{total}, passed {len(results)}")

        logger.info(f"✅ Screen complete: {len(results)}/{total} passed")
        return results

    def quick_screen(
        self,
        tickers: List[str],
        max_workers: int = 30,
    ) -> List[str]:
        """
        Fast screen (basic info only, no volatility backtest).
        Suitable for daily updates.
        """
        results = []

        def _quick(ticker: str) -> Optional[str]:
            try:
                from backend.data_engine.china_adapter import china_data_adapter
                quote = china_data_adapter.get_realtime_quote(ticker)
                if quote and quote.get("price", 0) >= 0.50:
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

        logger.info(f"⚡ Fast screen: {len(results)}/{len(tickers)}")
        return results

    # ================================================================
    # Cache
    # ================================================================

    def build(self, force: bool = False):
        """Build / refresh the cross-market universe."""
        # Check cache
        if not force and self._last_update:
            age = (datetime.now() - self._last_update).total_seconds()
            if age < 86400:  # within 24 hours
                logger.info(f"📦 Using cache ({len(self._all_stocks)} names, updated {age/3600:.1f}h ago)")
                return

        logger.info("🏗️ Building cross-market stock universe...")

        # 1. Fetch constituents
        us_raw = self.fetch_us_universe()
        hk_raw = self.fetch_hk_universe()
        sg_raw = self.fetch_sg_universe()
        au_raw = self.fetch_au_universe()
        nz_raw = self.fetch_nz_universe()
        cn_raw = self._fetch_cn_stocks()

        # 2. Screen (full pass first time, incremental afterwards)
        if not self._all_stocks or force:
            us_screened = self.screen_stocks(us_raw, max_workers=25)
            # yfinance is unreliable for HK/SG/AU/NZ; pass the list through (market_data uses tiger_open)
            hk_screened = [{"ticker": t, "name": t, "market_cap": 1e10, "avg_volume": 1e6, 
                           "price": 50, "volatility": 0.3, "beta": 1.0, "sector": "HK"}
                          for t in hk_raw]
            sg_screened = [{"ticker": t, "name": t, "market_cap": 1e10, "avg_volume": 1e6,
                           "price": 10, "volatility": 0.3, "beta": 1.0, "sector": "SG"}
                          for t in sg_raw]
            au_screened = [{"ticker": t, "name": t, "market_cap": 1e10, "avg_volume": 1e6,
                           "price": 50, "volatility": 0.3, "beta": 1.0, "sector": "AU"}
                          for t in au_raw]
            nz_screened = [{"ticker": t, "name": t, "market_cap": 1e9, "avg_volume": 5e5,
                           "price": 5, "volatility": 0.3, "beta": 1.0, "sector": "NZ"}
                          for t in nz_raw]
        else:
            us_screened = self.quick_screen(us_raw)
            hk_screened = [{"ticker": t, "name": t, "market_cap": 1e10, "avg_volume": 1e6,
                           "price": 50, "volatility": 0.3, "beta": 1.0, "sector": "HK"}
                          for t in hk_raw]
            sg_screened = [{"ticker": t, "name": t, "market_cap": 1e10, "avg_volume": 1e6,
                           "price": 10, "volatility": 0.3, "beta": 1.0, "sector": "SG"}
                          for t in sg_raw]
            au_screened = [{"ticker": t, "name": t, "market_cap": 1e10, "avg_volume": 1e6,
                           "price": 50, "volatility": 0.3, "beta": 1.0, "sector": "AU"}
                          for t in au_raw]
            nz_screened = [{"ticker": t, "name": t, "market_cap": 1e9, "avg_volume": 5e5,
                           "price": 5, "volatility": 0.3, "beta": 1.0, "sector": "NZ"}
                          for t in nz_raw]

        # 3. Assemble
        self._us_stocks = us_screened
        self._hk_stocks = hk_screened
        self._sg_stocks = sg_screened
        self._au_stocks = au_screened
        self._nz_stocks = nz_screened
        cn_screened = [{"ticker": t, "name": t, "market_cap": 5e10, "avg_volume": 1e7,
                       "price": 30, "volatility": 0.35, "beta": 1.0, "sector": "CN"}
                      for t in cn_raw]
        self._cn_stocks = cn_screened
        self._all_stocks = us_screened + hk_screened + sg_screened + au_screened + nz_screened + cn_screened
        self._last_update = datetime.now()

        self._save_cache()

        logger.info(f"✅ Universe build complete: US {len(self._us_stocks)} + HK {len(self._hk_stocks)} "
                    f"+ SG {len(self._sg_stocks)} + AU {len(self._au_stocks)} + NZ {len(self._nz_stocks)} "
                    f"+ CN {len(self._cn_stocks)} = {len(self._all_stocks)} names")

    def _save_cache(self):
        data = {
            "last_update": self._last_update.isoformat() if self._last_update else None,
            "us_count": len(self._us_stocks),
            "hk_count": len(self._hk_stocks),
            "sg_count": len(self._sg_stocks),
            "au_count": len(self._au_stocks),
            "nz_count": len(self._nz_stocks),
            "cn_count": len(self._cn_stocks),
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
                # Use sector field from cached data, fallback to suffix heuristic
                def _by_sector(sector_val):
                    return [s for s in self._all_stocks if s.get("sector","") == sector_val]
                self._hk_stocks = _by_sector("HK")
                self._sg_stocks = _by_sector("SG")
                self._au_stocks = _by_sector("AU")
                self._nz_stocks = _by_sector("NZ")
                self._cn_stocks = _by_sector("CN")
                hk_sg_au_nz = set().union(*[set(s.get("ticker","") for s in lst) for lst in [self._hk_stocks, self._sg_stocks, self._au_stocks, self._nz_stocks, self._cn_stocks]])
                self._us_stocks = [s for s in self._all_stocks if s.get("ticker","") not in hk_sg_au_nz]
                if data.get("last_update"):
                    self._last_update = datetime.fromisoformat(data["last_update"])
                logger.info(f"📦 Loaded cache: {len(self._all_stocks)} names "
                           f"({data.get('us_count',0)} US + {data.get('hk_count',0)} HK "
                           f"+ {data.get('sg_count',0)} SG + {data.get('au_count',0)} AU "
                           f"+ {data.get('nz_count',0)} NZ + {data.get('cn_count',0)} CN)")
            except Exception as e:
                logger.warning(f"⚠️ Cache load failed: {e}")

    # ================================================================
    # Accessors
    # ================================================================

    @property
    def us_tickers(self) -> List[str]:
        return [s["ticker"] if isinstance(s, dict) else s for s in self._us_stocks]

    @property
    def hk_tickers(self) -> List[str]:
        raw = [s["ticker"] if isinstance(s, dict) else s for s in self._hk_stocks]
        return [t.replace(".HK","").zfill(5) if t.replace(".HK","").isdigit() else t for t in raw]

    @property
    def sg_tickers(self) -> List[str]:
        return [s["ticker"] if isinstance(s, dict) else s for s in self._sg_stocks]

    @property
    def au_tickers(self) -> List[str]:
        return [s["ticker"] if isinstance(s, dict) else s for s in self._au_stocks]

    @property
    def nz_tickers(self) -> List[str]:
        return [s["ticker"] if isinstance(s, dict) else s for s in self._nz_stocks]

    @property
    def cn_tickers(self) -> List[str]:
        """A-share tickers, already suffixed with .SH/.SZ."""
        return [s["ticker"] if isinstance(s, dict) else s for s in self._cn_stocks]

    @property
    def all_tickers(self) -> List[str]:
        """Tickers for enabled markets only (default: US)."""
        try:
            from configs.settings import settings

            markets = set(settings.enabled_markets_list)
        except Exception:
            markets = {"US"}

        out: List[str] = []
        if "US" in markets:
            out.extend(self.us_tickers)
        if "HK" in markets:
            out.extend(f"{t}.HK" for t in self.hk_tickers)
        if "SG" in markets:
            out.extend(self.sg_tickers)
        if "AU" in markets:
            out.extend(self.au_tickers)
        if "NZ" in markets:
            out.extend(self.nz_tickers)
        if "CN" in markets:
            out.extend(self.cn_tickers)
        return out

    def get_top_by(self, key: str = "market_cap", n: int = 50) -> List[Dict]:
        """Return the top N names sorted by a metric."""
        dict_stocks = [s for s in self._all_stocks if isinstance(s, dict)]
        sorted_stocks = sorted(dict_stocks, key=lambda x: x.get(key, 0) or 0, reverse=True)
        return sorted_stocks[:n]

    def get_high_volatility(self, n: int = 50) -> List[Dict]:
        """High-volatility names (more trading opportunities)."""
        dict_stocks = [s for s in self._all_stocks if isinstance(s, dict)]
        sorted_stocks = sorted(dict_stocks, key=lambda x: x.get("volatility", 0) or 0, reverse=True)
        return sorted_stocks[:n]

    def summary(self) -> Dict:
        """Universe summary."""
        return {
            "us_count": len(self._us_stocks),
            "hk_count": len(self._hk_stocks),
            "sg_count": len(self._sg_stocks),
            "au_count": len(self._au_stocks),
            "nz_count": len(self._nz_stocks),
            "cn_count": len(self._cn_stocks),
            "total": len(self._all_stocks),
            "last_update": self._last_update.isoformat() if self._last_update else None,
            "top_mcap": self.get_top_by("market_cap", 10),
            "top_volatile": self.get_high_volatility(10),
        }


# Global singleton
stock_universe = StockUniverse()


if __name__ == "__main__":
    print("🏗️ Building cross-market stock universe...")
    stock_universe.build(force=True)
    s = stock_universe.summary()
    print(f"\n📊 Universe overview:")
    print(f"   US: {s['us_count']} names")
    print(f"   HK: {s['hk_count']} names")
    print(f"   SG: {s['sg_count']} names")
    print(f"   AU: {s['au_count']} names")
    print(f"   NZ: {s['nz_count']} names")
    print(f"   Total: {s['total']} names")
    print(f"\n📈 Top 10 by market cap:")
    for st in s["top_mcap"][:10]:
        cap_b = st.get("market_cap", 0) / 1e9 if st.get("market_cap") else 0
        print(f"   {st['ticker']:10s} {st.get('name',''):30s} ${cap_b:.1f}B")
