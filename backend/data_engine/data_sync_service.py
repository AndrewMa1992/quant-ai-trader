"""
Data-sync orchestrator.
Coordinates Tier 1/2/3 sync plus all-time full history pulls.
Integrates rate_limiter, sync_manager, tiger_client, and historical_store
into a single sync entry point.
"""
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from loguru import logger

from configs.settings import settings
from backend.data_engine.rate_limiter import rate_limiter
from backend.data_engine.sync_manager import SyncManager
from backend.data_engine.historical_store import HistoricalStore


class DataSyncService:
    """
    Data-sync orchestrator.

    Architecture:
        ┌─────────────────────────────────────┐
        │  DataSyncService (orchestrator)      │
        │  ├── tier1_sync()  → 30s loop       │
        │  ├── tier2_sync()  → 5min loop      │
        │  ├── tier3_sync()  → daily          │
        │  └── alltime_sync() → first run     │
        └──────────┬──────────────────────────┘
                   │
        ┌──────────┼──────────────────┐
        │  rate_limiter  sync_manager │
        │  tiger_client  hist_store   │
        └─────────────────────────────┘

    Usage:
        svc = DataSyncService(tiger_client, store)
        svc.start()           # start background sync
        svc.run_alltime()     # full initialization
        svc.stop()            # stop
    """

    # ================================================================
    # Limits
    # ================================================================

    TIER1_INTERVAL = 30          # high frequency: 30s
    TIER2_INTERVAL = 300         # mid frequency: 5 minutes
    TIER3_INTERVAL = 86400       # low frequency: 24 hours
    ALLTIME_BATCH_SIZE = 200     # all-time batch size
    ALLTIME_DELAY_BETWEEN = 6.0  # delay between all-time batches (seconds)

    def __init__(self, tiger_client, store: Optional[HistoricalStore] = None):
        """
        Args:
            tiger_client: TigerClient instance
            store: HistoricalStore instance (pass an existing one to reuse the connection)
        """
        self._tiger = tiger_client
        self._store = store or HistoricalStore()
        self._sync_mgr = SyncManager()

        # Thread control
        self._running = False
        self._threads: List[threading.Thread] = []
        self._alltime_running = False
        self._lock = threading.Lock()

        # Stats
        self.stats = {
            "tier1_runs": 0,
            "tier2_runs": 0,
            "tier3_runs": 0,
            "alltime_runs": 0,
            "errors": 0,
            "last_tier1": None,
            "last_tier2": None,
            "last_tier3": None,
            "last_alltime": None,
        }

        logger.info("DataSyncService initialized")

    # ================================================================
    # Start / stop
    # ================================================================

    def start(self):
        """Start background sync loops (non-blocking)."""
        if self._running:
            logger.warning("DataSyncService is already running")
            return

        self._running = True

        # Start per-tier sync threads
        t1 = threading.Thread(target=self._tier1_loop, daemon=True, name="tier1-sync")
        t2 = threading.Thread(target=self._tier2_loop, daemon=True, name="tier2-sync")
        t3 = threading.Thread(target=self._tier3_loop, daemon=True, name="tier3-sync")

        self._threads = [t1, t2, t3]
        t1.start()
        t2.start()
        t3.start()

        logger.info("🚀 DataSyncService started (Tier1: 30s, Tier2: 5min, Tier3: daily)")

    def stop(self):
        """Stop background sync."""
        self._running = False
        for t in self._threads:
            t.join(timeout=10)
        self._threads.clear()
        logger.info("⏹ DataSyncService stopped")

    # ================================================================
    # Tier 1 — high-frequency sync (30s)
    # ================================================================

    def _tier1_loop(self):
        """Tier 1 background loop."""
        while self._running:
            try:
                self.tier1_sync()
            except Exception as e:
                logger.error(f"Tier1 exception: {e}")
                self.stats["errors"] += 1
            time.sleep(self.TIER1_INTERVAL)

    def tier1_sync(self) -> Dict:
        """
        Tier 1: high-frequency sync (30s).
        - Position realtime quotes (batch get_stock_briefs)
        - Open-order status
        """
        if not self._tiger.is_connected():
            logger.debug("Tier1: Tiger not connected, skipping")
            return {"status": "skipped", "reason": "not_connected"}

        self._sync_mgr.start_sync("tier1")
        start = time.time()

        try:
            # Positions determine which quotes to fetch
            positions = self._tiger.get_positions()
            tickers = [p["ticker"] for p in positions] if positions else []

            # Merge configured watch list
            watch_tickers = list(set(
                tickers + settings.DATA_ALL_TICKERS[:20]
            ))[:50]  # max 50 names

            prices = {}
            if watch_tickers:
                # Batch quotes (1 call = 50 names)
                for batch_idx in range(0, len(watch_tickers), 50):
                    batch = watch_tickers[batch_idx:batch_idx + 50]
                    quote = self._tiger.get_quote(batch[0])  # get_stock_briefs is inside get_quote
                    if quote:
                        prices[batch[0]] = quote["price"]

                        # Fetch remaining prices in the batch
                        for ticker in batch[1:]:
                            try:
                                q = self._tiger.get_quote(ticker)
                                if q:
                                    prices[ticker] = q["price"]
                            except Exception:
                                pass

            # Persist price snapshot
            if prices:
                self._store.save_price_ticks_batch(prices)

            # Sync open orders (unfilled order status)
            open_orders = self._tiger.get_open_orders()
            if open_orders:
                self._store.save_tiger_orders_batch(open_orders)

            elapsed = time.time() - start
            self._sync_mgr.mark_success("tier1", records=len(prices))

            self.stats["tier1_runs"] += 1
            self.stats["last_tier1"] = datetime.now().isoformat()

            logger.debug(
                f"Tier1 complete: {len(prices)} prices, {len(open_orders)} open orders "
                f"({elapsed:.1f}s)"
            )

            return {
                "status": "success",
                "prices": len(prices),
                "open_orders": len(open_orders),
                "elapsed": round(elapsed, 2),
            }

        except Exception as e:
            self._sync_mgr.mark_error("tier1", str(e))
            self.stats["errors"] += 1
            logger.error(f"Tier1 sync failed: {e}")
            return {"status": "error", "error": str(e)}

    # ================================================================
    # Tier 2 — mid-frequency sync (5min)
    # ================================================================

    def _tier2_loop(self):
        """Tier 2 background loop."""
        # Delay 10s on first start so it does not fire with Tier1
        time.sleep(10)
        while self._running:
            try:
                self.tier2_sync()
            except Exception as e:
                logger.error(f"Tier2 exception: {e}")
                self.stats["errors"] += 1
            time.sleep(self.TIER2_INTERVAL)

    def tier2_sync(self) -> Dict:
        """
        Tier 2: mid-frequency sync (5min).
        - Capital flow
        - Order-book depth (top 10)
        - Short interest
        - Account segment assets
        """
        if not self._tiger.is_connected():
            return {"status": "skipped", "reason": "not_connected"}

        self._sync_mgr.start_sync("tier2")
        start = time.time()
        results = {}

        try:
            # Active ticker list
            positions = self._tiger.get_positions()
            tickers = [p["ticker"] for p in positions] if positions else []
            # Supplement from the configured watch list
            active_tickers = tickers[:15] + list(settings.DATA_ALL_TICKERS[:10])
            active_tickers = list(dict.fromkeys(active_tickers))[:20]  # de-dupe, max 20

            # 1. Capital flow (3 batches of ~7 names)
            if rate_limiter.can_call():
                flow_results = []
                for ticker in active_tickers[:10]:
                    if not self._running:
                        break
                    try:
                        flow = self._tiger.get_capital_flow(ticker)
                        if flow:
                            flow_results.append(flow)
                    except Exception:
                        pass
                if flow_results:
                    self._store.save_capital_flow_batch(flow_results)
                    results["capital_flow"] = len(flow_results)

            # 2. Order-book depth (top 10 active names)
            if rate_limiter.can_call():
                depth_count = 0
                for ticker in active_tickers[:10]:
                    if not self._running:
                        break
                    try:
                        depth = self._tiger.get_depth_quote(ticker)
                        if depth:
                            depth_count += 1
                    except Exception:
                        pass
                results["depth_quote"] = depth_count

            # 3. Short interest
            if rate_limiter.can_call():
                short_count = 0
                for ticker in active_tickers[:5]:
                    if not self._running:
                        break
                    try:
                        si = self._tiger.get_short_interest(ticker)
                        if si:
                            short_count += 1
                    except Exception:
                        pass
                results["short_interest"] = short_count

            # 4. Account segment assets
            if rate_limiter.can_call():
                segments = self._tiger.get_account_segments()
                if segments:
                    results["account_segments"] = len(segments)

            elapsed = time.time() - start
            self._sync_mgr.mark_success(
                "tier2",
                records=sum(results.values())
            )

            self.stats["tier2_runs"] += 1
            self.stats["last_tier2"] = datetime.now().isoformat()

            logger.info(
                f"Tier2 complete: {results} ({elapsed:.1f}s)"
            )

            return {"status": "success", "results": results, "elapsed": round(elapsed, 2)}

        except Exception as e:
            self._sync_mgr.mark_error("tier2", str(e))
            self.stats["errors"] += 1
            logger.error(f"Tier2 sync failed: {e}")
            return {"status": "error", "error": str(e)}

    # ================================================================
    # Tier 3 — low-frequency sync (daily)
    # ================================================================

    def _tier3_loop(self):
        """Tier 3 background loop."""
        # Delay on first start until the system is stable
        time.sleep(60)
        while self._running:
            try:
                self.tier3_sync()
            except Exception as e:
                logger.error(f"Tier3 exception: {e}")
                self.stats["errors"] += 1
            # Recheck hourly whether a run is due
            for _ in range(3600):
                if not self._running:
                    break
                time.sleep(1)

    def tier3_sync(self) -> Dict:
        """
        Tier 3: low-frequency sync (once pre-open and once post-close each day).
        - Fundamentals
        - Trading calendar
        - Corporate events (dividends / splits / earnings)
        """
        if not self._tiger.is_connected():
            return {"status": "skipped", "reason": "not_connected"}

        # Skip if already run today
        today = datetime.now().strftime("%Y-%m-%d")
        last_status = self._sync_mgr.get_last_sync("tier3")
        if last_status["last_success_time"] and today in str(last_status["last_success_time"]):
            logger.debug(f"Tier3: already ran today, skipping")
            return {"status": "skipped", "reason": "already_done_today"}

        self._sync_mgr.start_sync("tier3")
        start = time.time()
        results = {}

        try:
            all_tickers = settings.DATA_ALL_TICKERS

            # 1. Fundamentals (batched)
            if rate_limiter.can_call():
                meta_saved = 0
                for batch_idx in range(0, len(all_tickers), 20):
                    batch = all_tickers[batch_idx:batch_idx + 20]
                    fundamentals = self._tiger.get_stock_fundamentals(batch)
                    if fundamentals:
                        self._store.save_stock_metadata_batch(fundamentals)
                        meta_saved += len(fundamentals)
                    if batch_idx + 20 < len(all_tickers):
                        time.sleep(2)  # inter-batch delay
                results["fundamentals"] = meta_saved

            # 2. Trading calendar (US)
            if rate_limiter.can_call():
                calendar = self._tiger.get_trading_calendar("US")
                if calendar:
                    self._store.save_market_calendar_batch(calendar)
                    results["calendar_US"] = len(calendar)

            # 3. HK trading calendar
            if rate_limiter.can_call():
                calendar_hk = self._tiger.get_trading_calendar("HK")
                if calendar_hk:
                    self._store.save_market_calendar_batch(calendar_hk)
                    results["calendar_HK"] = len(calendar_hk)

            # 4. Corporate events (dividends / splits / earnings)
            if rate_limiter.can_call():
                events = self._tiger.get_corporate_events_batch(all_tickers[:15])
                if events:
                    self._store.save_corporate_events_batch(events)
                    results["corporate_events"] = len(events)

            elapsed = time.time() - start
            self._sync_mgr.mark_success(
                "tier3",
                records=sum(results.values())
            )

            self.stats["tier3_runs"] += 1
            self.stats["last_tier3"] = datetime.now().isoformat()

            logger.info(f"Tier3 complete: {results} ({elapsed:.1f}s)")

            return {"status": "success", "results": results, "elapsed": round(elapsed, 2)}

        except Exception as e:
            self._sync_mgr.mark_error("tier3", str(e))
            self.stats["errors"] += 1
            logger.error(f"Tier3 sync failed: {e}")
            return {"status": "error", "error": str(e)}

    # ================================================================
    # All-Time — full history pull
    # ================================================================

    def run_alltime(self, force: bool = False) -> Dict:
        """
        Full historical pull (first deploy, or when a complete dataset is required).

        Run outside trading hours; typically 30-45 minutes.

        Args:
            force: force a run (ignore last_sync state)

        Returns:
            { status, orders, transactions, fundamentals, elapsed }
        """
        if self._alltime_running:
            logger.warning("All-Time sync is already running")
            return {"status": "skipped", "reason": "already_running"}

        if not self._tiger.is_connected():
            logger.error("All-Time: Tiger not connected")
            return {"status": "error", "reason": "not_connected"}

        # Check whether a full sync is needed
        if not force and not self._sync_mgr.needs_full_sync("alltime", max_age_hours=720):
            logger.info("All-Time: full sync not needed (already ran within 30 days)")
            return {"status": "skipped", "reason": "not_needed"}

        self._alltime_running = True
        self._sync_mgr.start_sync("alltime")
        start = time.time()
        results = {}

        try:
            # 1. Historical orders (paged)
            logger.info("📥 All-Time Phase 1/5: pulling historical orders...")
            all_orders = []
            page = 0
            while True:
                orders = self._tiger.get_orders_history(
                    limit=self.ALLTIME_BATCH_SIZE,
                )
                if not orders:
                    break
                all_orders.extend(orders)
                page += 1
                logger.info(f"  Orders page {page}: {len(orders)} rows, cumulative {len(all_orders)}")
                if len(orders) < self.ALLTIME_BATCH_SIZE:
                    break
                time.sleep(self.ALLTIME_DELAY_BETWEEN)

            if all_orders:
                self._store.save_tiger_orders_batch(all_orders)
            results["orders"] = len(all_orders)

            # 2. Fills / transactions (paged)
            logger.info("📥 All-Time Phase 2/5: pulling fill details...")
            all_transactions = []
            page = 0
            while True:
                trans = self._tiger.get_transactions(
                    limit=self.ALLTIME_BATCH_SIZE,
                )
                if not trans:
                    break
                all_transactions.extend(trans)
                page += 1
                logger.info(f"  Fills page {page}: {len(trans)} rows, cumulative {len(all_transactions)}")
                if len(trans) < self.ALLTIME_BATCH_SIZE:
                    break
                time.sleep(self.ALLTIME_DELAY_BETWEEN)

            if all_transactions:
                self._store.save_tiger_transactions_batch(all_transactions)
            results["transactions"] = len(all_transactions)

            # 3. Filled orders
            logger.info("📥 All-Time Phase 3/5: pulling filled orders...")
            filled_orders = self._tiger.get_filled_orders()
            if filled_orders:
                self._store.save_tiger_orders_batch(filled_orders)
                results["filled_orders"] = len(filled_orders)

            # 4. Cancelled orders
            logger.info("📥 All-Time Phase 4/5: pulling cancelled orders...")
            cancelled = self._tiger.get_cancelled_orders()
            if cancelled:
                self._store.save_tiger_orders_batch(cancelled)
                results["cancelled_orders"] = len(cancelled)

            # 5. Full fundamentals
            logger.info("📥 All-Time Phase 5/5: pulling full fundamentals...")
            all_tickers = settings.DATA_ALL_TICKERS
            all_fundamentals = []
            for batch_idx in range(0, len(all_tickers), 20):
                batch = all_tickers[batch_idx:batch_idx + 20]
                fundamentals = self._tiger.get_stock_fundamentals(batch)
                if fundamentals:
                    all_fundamentals.extend(fundamentals)
                if batch_idx + 20 < len(all_tickers):
                    time.sleep(3)

            if all_fundamentals:
                self._store.save_stock_metadata_batch(all_fundamentals)
            results["fundamentals"] = len(all_fundamentals)

            elapsed = time.time() - start
            self._sync_mgr.mark_success("alltime", records=sum(results.values()))

            self.stats["alltime_runs"] += 1
            self.stats["last_alltime"] = datetime.now().isoformat()

            logger.info(
                f"✅ All-Time complete: {results} ({elapsed:.0f}s = {elapsed/60:.1f}min)"
            )

            return {
                "status": "success",
                "results": results,
                "elapsed": round(elapsed, 2),
            }

        except Exception as e:
            self._sync_mgr.mark_error("alltime", str(e))
            self.stats["errors"] += 1
            logger.error(f"All-Time sync failed: {e}")
            return {"status": "error", "error": str(e)}

        finally:
            self._alltime_running = False

    # ================================================================
    # Status & stats
    # ================================================================

    def get_status(self) -> Dict:
        """Return service status."""
        all_status = self._sync_mgr.get_all_sync_status()
        return {
            "running": self._running,
            "alltime_running": self._alltime_running,
            "rate_limiter": rate_limiter.get_stats(),
            "sync_status": all_status,
            "stats": dict(self.stats),
        }

    def is_syncing(self) -> bool:
        """Return whether any sync is in progress."""
        return self._alltime_running or any(
            self._sync_mgr.is_syncing(t)
            for t in ["tier1", "tier2", "tier3"]
        )
