"""
Lot Predictor + Capital Filter.

Capabilities:
1. Look up / predict each market's minimum trade unit (lot size)
2. Compute the minimum capital to buy (local currency + USD equivalent)
3. Auto-exclude names that cannot be afforded, saving AI inference time
4. Expanded HK lot coverage (known table + Tiger API lookup)

P2: universe scan + auto FX + lot prediction + capital filter
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from loguru import logger
from configs.settings import settings


class LotPredictor:
    """Lot predictor — look up each market's minimum trade unit."""

    # ═══════════════════════════════════════════
    # HK lot-size table (extended)
    # ═══════════════════════════════════════════
    HK_LOT_SIZES: Dict[str, int] = {
        # Large-cap blue chips (index constituents)
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

    # Default lot sizes
    DEFAULT_LOT = {
        "US": 1,
        "HK": 100,   # HK default 100 shares
        "SG": 100,   # Singapore default 100 shares
        "AU": 1,
        "NZ": 1,
    }

    def __init__(self):
        self._tiger_lot_cache: Dict[str, int] = {}
        self._last_tiger_query: float = 0

    # ── Main: get lot size ──
    def get_lot_size(
        self,
        ticker: str,
        market: str = "US",
        tiger_client=None,
    ) -> int:
        """
        Return the minimum trade unit for a ticker.

        Priority:
        1. Known table (HK_LOT_SIZES)
        2. Tiger API lookup
        3. Market default

        Args:
            ticker: e.g. '00700', 'AAPL', 'D05.SI'
            market: US/HK/SG/AU/NZ
            tiger_client: TigerClient instance

        Returns:
            Minimum share quantity
        """
        # US/AU/NZ → 1 share
        if market in ("US", "AU", "NZ"):
            return 1

        # Singapore → default 100 shares
        if market == "SG":
            return 100

        # HK — strip ticker suffix
        clean = ticker.replace(".HK", "").replace(".hk", "")

        # 1. Known table
        if clean in self.HK_LOT_SIZES:
            return self.HK_LOT_SIZES[clean]

        # 2. Tiger API lookup
        if tiger_client and tiger_client.is_connected():
            lot = self._query_tiger_lot(clean, tiger_client)
            if lot > 0:
                self._tiger_lot_cache[clean] = lot
                return lot

        # 3. Default
        return self.DEFAULT_LOT.get(market, 100)

    def _query_tiger_lot(self, symbol: str, tiger_client) -> int:
        """Look up lot size from Tiger contract info."""
        import time
        now = time.time()

        # Cache (30 minutes)
        if symbol in self._tiger_lot_cache and (now - self._last_tiger_query) < 1800:
            return self._tiger_lot_cache[symbol]

        try:
            # Query via contract
            from tigeropen.common.contract import Contract
            from tigeropen.common.util.contract_utils import stock_contract

            contract = stock_contract(symbol, "HK")
            if contract and hasattr(contract, 'lot_size'):
                self._last_tiger_query = now
                return contract.lot_size
        except Exception:
            pass

        return 0  # Lookup failed

    # ── Capital threshold ──
    def calc_min_capital(
        self,
        ticker: str,
        price: float,
        market: str = "US",
        tiger_client=None,
    ) -> Dict:
        """
        Compute the minimum capital required to buy one lot.

        Args:
            ticker: Symbol
            price: Current price (local currency)
            market: Market code
            tiger_client: Tiger client

        Returns:
            {
                "ticker": str,
                "lot_size": int,         # Minimum trade unit
                "price_local": float,    # Unit price (local)
                "min_local": float,      # Min buy cost (local)
                "min_usd": float,        # Min buy cost (USD)
                "affordable": bool,      # Whether it is affordable
                "currency": str,         # Currency
            }
        """
        lot_size = self.get_lot_size(ticker, market, tiger_client)
        currency = self._get_currency(ticker, market)
        fx_rate = settings.trading_currency_rates_dict.get(currency, 1.0)

        min_local = price * lot_size
        # 0.5% commission buffer
        min_local *= 1.005
        min_usd = min_local * fx_rate

        return {
            "ticker": ticker,
            "lot_size": lot_size,
            "price_local": round(price, 4),
            "min_local": round(min_local, 2),
            "min_usd": round(min_usd, 2),
            "affordable": False,  # Filled by caller
            "currency": currency,
        }

    @staticmethod
    def _get_currency(ticker: str, market: str) -> str:
        """Infer currency from ticker and market."""
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

    # ── Batch capital filter ──
    def filter_affordable(
        self,
        tickers: List[str],
        prices: Dict[str, float],
        available_cash_usd: float,
        markets: Dict[str, str] = None,
        tiger_client=None,
    ) -> Tuple[List[str], Dict, List[str]]:
        """
        Batch filter — drop names that cannot be afforded.

        Args:
            tickers: Candidate ticker list
            prices: {ticker: price_local}
            available_cash_usd: Available cash across currencies (USD equivalent)
            markets: {ticker: market} map
            tiger_client: Tiger client

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

            # Same-currency cash check
            currency = detail["currency"]
            rate = settings.trading_currency_rates_dict.get(currency, 1.0)
            cash_in_ccy = available_cash_usd / rate if rate > 0 else 0

            if cash_in_ccy >= detail["min_local"]:
                detail["affordable"] = True
                affordable.append(ticker)
            else:
                detail["affordable"] = False
                excluded.append(ticker)
                logger.debug(f"  🚫 {ticker}: needs {currency} {detail['min_local']:.0f}, "
                           f"only {currency} {cash_in_ccy:.0f}")

            capital_detail[ticker] = detail

        if excluded:
            logger.info(f"💰 Capital filter: {len(affordable)} affordable, {len(excluded)} excluded")

        return affordable, capital_detail, excluded

    # ── Pre-filter before AI inference ──
    def pre_filter_for_ai(
        self,
        universe: List[Dict],
        available_cash_usd: float,
        n_top: int = 100,
    ) -> List[str]:
        """
        Pre-filter before AI inference — keep only the affordable Top-N names.

        Cuts AI cost by skipping names that cannot be traded.

        Args:
            universe: Full scan result (market_scanner affordable list)
            available_cash_usd: Available cash in USD equivalent
            n_top: Max names to return

        Returns:
            Filtered ticker list (priority-sorted)
        """
        candidates = []

        for entry in universe:
            min_cap = entry.get("min_capital_usd", 0)
            if min_cap <= 0:
                # No price info → keep
                candidates.append(entry)
            elif available_cash_usd >= min_cap:
                # Affordable
                candidates.append(entry)
            else:
                # Unaffordable → skip
                pass

        # Sort: benchmark_weight descending
        candidates.sort(
            key=lambda x: (x.get("benchmark_weight", 0), x.get("volume", 0)),
            reverse=True
        )

        logger.info(f"🧹 AI pre-filter: {len(universe)} → {len(candidates[:n_top])} names "
                   f"(cash≥${available_cash_usd:,.0f})")

        return [c["ticker"] for c in candidates[:n_top]]

    # ── HK lot-coverage stats ──
    def get_hk_lot_coverage(self, tickers: List[str]) -> Dict:
        """Summarize HK lot-size coverage."""
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


# Global singleton
lot_predictor = LotPredictor()
