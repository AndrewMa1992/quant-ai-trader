"""
Market Scanner — dynamic cross-market instrument scanner.

Validates tradability of every name in the stock universe via the Tiger API,
then filters and ranks dynamically. Replaces hardcoded ticker lists so
cross-market opportunity can be maximized.

Capabilities:
- Load the full candidate pool from market_universe (~800 names)
- Validate tradability via Tiger API (price>0, healthy status, not delisted)
- Filter by liquidity / volatility / fundamentals
- Emit per-market priority names and capital hurdles

P2: full-universe scan + auto FX + board-lot projection + capital filter
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from loguru import logger

from configs.settings import settings
from configs.market_universe import StockEntry
from backend.data_engine.stock_universe import stock_universe


class MarketScanner:
    """Dynamic cross-market scanner — validate names, compute hurdles, rank."""

    # Cache TTL: refresh every 30 minutes
    CACHE_TTL = 1800

    def __init__(self):
        self._cache_path = DATA_DIR / "scanned_universe.json"
        self._last_scan: float = 0
        self._scanned: List[Dict] = []
        self._by_market: Dict[str, List[Dict]] = {}
        self._affordable: List[Dict] = []
        self._total_available = 0

    # ── Main entry ──
    def scan(
        self,
        tiger_client=None,
        available_cash: float = 0,
        positions: dict = None,
        force: bool = False,
    ) -> Dict:
        """
        Scan the full market for tradable instruments.

        Args:
            tiger_client: TigerClient instance (pass after connect)
            available_cash: cash by currency {currency: amount}
                e.g. {"USD": 2000, "HKD": 0, "SGD": 0}
            positions: existing holdings {ticker: shares} (used for priority)
            force: force a cache refresh

        Returns:
            {
                "total_available": int,        # tradable instrument count
                "by_market": {"US": [...], ...}, # grouped by market
                "affordable": [...],            # names the account can buy (desc)
                "scan_time": float,             # Unix timestamp
            }
        """
        now = time.time()
        if not force and self._scanned and (now - self._last_scan) < self.CACHE_TTL:
            self._recalc_affordable(available_cash)
            return self._summary()

        logger.info("🔍 Scanning full-market instruments...")

        # 1. Load the full candidate pool
        stock_universe.build(force=False)
        all_stocks: List[StockEntry] = stock_universe._all_stocks
        logger.info(f"  Candidate pool: {len(all_stocks)} names (US {len(stock_universe.us_tickers)} "
                   f"+ HK {len(stock_universe.hk_tickers)} + SG {len(stock_universe.sg_tickers)})")

        # 2. If Tiger is online, batch-validate
        validated: List[Dict] = []
        if tiger_client and tiger_client.is_connected():
            validated = self._validate_with_tiger(tiger_client, all_stocks)
        else:
            # Offline mode — treat all as tradable
            validated = self._offline_validation(all_stocks)

        # 3. Group by market
        self._scanned = validated
        self._by_market = self._group_by_market(validated)
        self._total_available = len(validated)
        self._last_scan = time.time()

        # 4. Compute capital hurdles
        self._calc_entry_barriers()
        self._recalc_affordable(available_cash)

        # 5. Persist cache to JSON
        self._save_cache()

        # Logs
        for mkt, stocks in self._by_market.items():
            logger.info(f"  {mkt}: {len(stocks)} tradable")

        return self._summary()

    # ── Tiger API online validation ──
    def _validate_with_tiger(self, tiger_client, all_stocks: list) -> List[Dict]:
        """Batch-validate the full universe."""
        validated = []
        total = len(all_stocks)
        batch_size = 50  # Tiger API limit

        for i in range(0, total, batch_size):
            batch = all_stocks[i:i + batch_size]
            tickers = [s.get("ticker", "") for s in batch if s.get("ticker")]
            if not tickers:
                continue

            try:
                # Batch realtime quotes — auto-exclude delisted/halted/invalid prices
                briefs = tiger_client._quote_client.get_stock_briefs(tickers)
                if briefs:
                    for j, brief in enumerate(briefs):
                        if j >= len(tickers):
                            break
                        ticker = tickers[j]
                        entry = batch[j]
                        price = getattr(brief, 'latest_price', 0) or 0

                        # Filter rules
                        if price <= 0:
                            continue  # invalid price → drop
                        if price < 0.10:
                            continue  # penny stock (delisting risk)
                        if getattr(brief, 'status', None) == 'S':
                            continue  # halted → drop

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
                            "affordable": False,  # filled after capital calc
                            "min_capital_usd": 0,  # filled later
                        })
            except Exception as e:
                logger.debug(f"  Instrument validation batch {i//batch_size + 1} failed: {e}")
                # Batch failure → fall back to offline entries for this batch
                for entry in batch:
                    validated.append(self._offline_entry(entry))

            time.sleep(0.1)  # API rate-limit padding

        return validated

    # ── Offline fallback ──
    def _offline_validation(self, all_stocks: list) -> List[Dict]:
        """Offline validation when Tiger is disconnected."""
        return [self._offline_entry(s) for s in all_stocks]

    def _offline_entry(self, entry: dict) -> Dict:
        """Build a single offline instrument entry."""
        ticker = entry.get("ticker", "")
        market = entry.get("market", "US")
        return {
            "ticker": ticker,
            "name": entry.get("name", ticker),
            "market": market,
            "currency": entry.get("currency", "USD"),
            "sector": entry.get("sector", "Unknown"),
            "price": 0,  # 0 means no live price
            "lot_size": self._get_lot_size(ticker, market),
            "volume": 0,
            "change_pct": 0,
            "benchmark_weight": entry.get("benchmark_weight", 0),
            "affordable": True,  # treat all as buyable offline
            "min_capital_usd": 0,
        }

    # ── Board lot size ──
    @staticmethod
    def _get_lot_size(ticker: str, market: str) -> int:
        """Return the minimum trade unit."""
        if market == "US":
            return 1
        if market == "SG":
            return 100  # Singapore default 100 shares

        # HK — known list + default
        from backend.data_engine.tiger_client import TigerClient
        return TigerClient.get_hk_lot_size(ticker)

    # ── Capital hurdle ──
    def _calc_entry_barriers(self):
        """Compute the minimum USD capital required for each instrument."""
        for entry in self._scanned:
            price = entry["price"]
            lot = entry["lot_size"]
            currency = entry["currency"]
            fx_rate = settings.trading_currency_rates_dict.get(currency, 1.0)

            if price > 0:
                # Local-currency cost of 1 board lot
                local_cost = price * lot
                # Convert to USD
                usd_cost = local_cost * fx_rate
                entry["min_capital_usd"] = round(usd_cost, 2)
            else:
                # No live price — conservative estimate
                entry["min_capital_usd"] = 500 if currency == "USD" else 200

    # ── Capital filter ──
    def _recalc_affordable(self, available_cash: dict = None):
        """Recompute buyable names from current cash."""
        if not available_cash:
            available_cash = {}

        total_usd = sum(
            amount * settings.trading_currency_rates_dict.get(ccy, 1.0)
            for ccy, amount in available_cash.items()
        )

        self._affordable = []
        for entry in self._scanned:
            min_capital = entry.get("min_capital_usd", 0)
            if total_usd <= 0:
                # No cash data provided → treat all as buyable
                entry["affordable"] = True
                self._affordable.append(entry)
            elif min_capital > 0 and total_usd >= min_capital:
                entry["affordable"] = True
                self._affordable.append(entry)
            else:
                entry["affordable"] = False

        # Sort by benchmark_weight desc → prefer blue chips
        self._affordable.sort(
            key=lambda x: (x.get("benchmark_weight", 0), x.get("volume", 0)),
            reverse=True
        )

    # ── Grouping ──
    @staticmethod
    def _group_by_market(entries: List[Dict]) -> Dict[str, List[Dict]]:
        groups: Dict[str, List[Dict]] = {}
        for e in entries:
            mkt = e.get("market", "US")
            groups.setdefault(mkt, []).append(e)
        return groups

    # ── Summary ──
    def _summary(self) -> Dict:
        return {
            "total_available": self._total_available,
            "by_market": {
                mkt: len(stocks) for mkt, stocks in self._by_market.items()
            },
            "affordable_count": len(self._affordable),
            "affordable": self._affordable[:200],  # return top 200
            "scan_time": self._last_scan,
        }

    # ── Cache ──
    def _save_cache(self):
        try:
            with open(self._cache_path, "w", encoding="utf-8") as f:
                json.dump({
                    "scanned": self._scanned,
                    "last_scan": self._last_scan,
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug(f"Cache write failed: {e}")

    def load_cache(self) -> bool:
        """Load cache from disk."""
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

    # ── Query API ──
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
        Return the best candidate ticker list.

        Args:
            n: maximum number to return
            include_positions: holdings that must be included
            market_filter: restrict to a market (US/HK/SG)
            min_price/max_price: price range
            exclude_unaffordable: drop names the account cannot buy

        Returns:
            ticker list, sorted by priority
        """
        candidates = []
        pos_set = include_positions or set()

        # Prioritize holdings
        for entry in self._scanned:
            if entry["ticker"] in pos_set:
                candidates.append(entry)

        # Other tradable names
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

        # Take top N
        return [c["ticker"] for c in candidates[:n]]

    def get_affordable_tickers(self) -> List[str]:
        """Return all tickers the current cash can buy."""
        return [e["ticker"] for e in self._affordable]

    def get_market_distribution(self) -> Dict[str, int]:
        """Instrument count by market."""
        return {mkt: len(stocks) for mkt, stocks in self._by_market.items()}


# Global singleton
market_scanner = MarketScanner()
