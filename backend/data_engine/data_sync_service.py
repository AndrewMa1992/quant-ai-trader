"""
数据同步协调服务
协调 Tier 1/2/3 同步 + All-Time 全量历史拉取。
集成 rate_limiter、sync_manager、tiger_client、historical_store，
提供统一的同步入口。
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
    数据同步协调器

    架构:
        ┌─────────────────────────────────────┐
        │  DataSyncService (orchestrator)      │
        │  ├── tier1_sync()  → 30s 循环       │
        │  ├── tier2_sync()  → 5min 循环      │
        │  ├── tier3_sync()  → daily          │
        │  └── alltime_sync() → 首次运行      │
        └──────────┬──────────────────────────┘
                   │
        ┌──────────┼──────────────────┐
        │  rate_limiter  sync_manager │
        │  tiger_client  hist_store   │
        └─────────────────────────────┘

    用法:
        svc = DataSyncService(tiger_client, store)
        svc.start()           # 启动后台同步
        svc.run_alltime()     # 全量初始化
        svc.stop()            # 停止
    """

    # ================================================================
    # 上限配置
    # ================================================================

    TIER1_INTERVAL = 30          # 高频：30秒
    TIER2_INTERVAL = 300         # 中频：5分钟
    TIER3_INTERVAL = 86400       # 低频：24小时
    ALLTIME_BATCH_SIZE = 200     # 全量每批获取数
    ALLTIME_DELAY_BETWEEN = 6.0  # 全量批间延迟（秒）

    def __init__(self, tiger_client, store: Optional[HistoricalStore] = None):
        """
        Args:
            tiger_client: TigerClient 实例
            store: HistoricalStore 实例（可传入已有实例复用连接）
        """
        self._tiger = tiger_client
        self._store = store or HistoricalStore()
        self._sync_mgr = SyncManager()

        # 线程控制
        self._running = False
        self._threads: List[threading.Thread] = []
        self._alltime_running = False
        self._lock = threading.Lock()

        # 统计
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

        logger.info("DataSyncService 初始化完成")

    # ================================================================
    # 启动 / 停止
    # ================================================================

    def start(self):
        """启动后台同步循环（非阻塞）"""
        if self._running:
            logger.warning("DataSyncService 已在运行中")
            return

        self._running = True

        # 启动各层同步线程
        t1 = threading.Thread(target=self._tier1_loop, daemon=True, name="tier1-sync")
        t2 = threading.Thread(target=self._tier2_loop, daemon=True, name="tier2-sync")
        t3 = threading.Thread(target=self._tier3_loop, daemon=True, name="tier3-sync")

        self._threads = [t1, t2, t3]
        t1.start()
        t2.start()
        t3.start()

        logger.info("🚀 DataSyncService 已启动 (Tier1: 30s, Tier2: 5min, Tier3: daily)")

    def stop(self):
        """停止后台同步"""
        self._running = False
        for t in self._threads:
            t.join(timeout=10)
        self._threads.clear()
        logger.info("⏹ DataSyncService 已停止")

    # ================================================================
    # Tier 1 — 高频同步 (30s)
    # ================================================================

    def _tier1_loop(self):
        """Tier 1 后台循环"""
        while self._running:
            try:
                self.tier1_sync()
            except Exception as e:
                logger.error(f"Tier1 异常: {e}")
                self.stats["errors"] += 1
            time.sleep(self.TIER1_INTERVAL)

    def tier1_sync(self) -> Dict:
        """
        Tier 1: 高频同步（30s）
        - 持仓实时报价 (批量 get_stock_briefs)
        - 当前挂单状态
        """
        if not self._tiger.is_connected():
            logger.debug("Tier1: Tiger 未连接，跳过")
            return {"status": "skipped", "reason": "not_connected"}

        self._sync_mgr.start_sync("tier1")
        start = time.time()

        try:
            # 获取持仓列表以确定需要获取报价的股票
            positions = self._tiger.get_positions()
            tickers = [p["ticker"] for p in positions] if positions else []

            # 合并配置的关注列表
            watch_tickers = list(set(
                tickers + settings.DATA_ALL_TICKERS[:20]
            ))[:50]  # 最多50只

            prices = {}
            if watch_tickers:
                # 批量获取报价（1 call = 50 只）
                for batch_idx in range(0, len(watch_tickers), 50):
                    batch = watch_tickers[batch_idx:batch_idx + 50]
                    quote = self._tiger.get_quote(batch[0])  # get_stock_briefs 在 get_quote 内部调用
                    if quote:
                        prices[batch[0]] = quote["price"]

                        # 批量获取整批的价格
                        for ticker in batch[1:]:
                            try:
                                q = self._tiger.get_quote(ticker)
                                if q:
                                    prices[ticker] = q["price"]
                            except Exception:
                                pass

            # 保存价格快照
            if prices:
                self._store.save_price_ticks_batch(prices)

            # 同步当前挂单（获取未成交订单状态）
            open_orders = self._tiger.get_open_orders()
            if open_orders:
                self._store.save_tiger_orders_batch(open_orders)

            elapsed = time.time() - start
            self._sync_mgr.mark_success("tier1", records=len(prices))

            self.stats["tier1_runs"] += 1
            self.stats["last_tier1"] = datetime.now().isoformat()

            logger.debug(
                f"Tier1 完成: {len(prices)} prices, {len(open_orders)} open orders "
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
            logger.error(f"Tier1 同步失败: {e}")
            return {"status": "error", "error": str(e)}

    # ================================================================
    # Tier 2 — 中频同步 (5min)
    # ================================================================

    def _tier2_loop(self):
        """Tier 2 后台循环"""
        # 首次启动延迟 10 秒，避免与 Tier1 同时触发
        time.sleep(10)
        while self._running:
            try:
                self.tier2_sync()
            except Exception as e:
                logger.error(f"Tier2 异常: {e}")
                self.stats["errors"] += 1
            time.sleep(self.TIER2_INTERVAL)

    def tier2_sync(self) -> Dict:
        """
        Tier 2: 中频同步（5min）
        - 资金流向
        - 订单簿深度 (Top 10)
        - 做空数据
        - 账户细分资产
        """
        if not self._tiger.is_connected():
            return {"status": "skipped", "reason": "not_connected"}

        self._sync_mgr.start_sync("tier2")
        start = time.time()
        results = {}

        try:
            # 获取活跃股票列表
            positions = self._tiger.get_positions()
            tickers = [p["ticker"] for p in positions] if positions else []
            # 补充配置中的关注列表
            active_tickers = tickers[:15] + list(settings.DATA_ALL_TICKERS[:10])
            active_tickers = list(dict.fromkeys(active_tickers))[:20]  # 去重，最多20只

            # 1. 资金流向（分3批，每批~7只）
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

            # 2. 订单簿深度（Top 10 活跃股）
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

            # 3. 做空数据
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

            # 4. 账户细分资产
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
                f"Tier2 完成: {results} ({elapsed:.1f}s)"
            )

            return {"status": "success", "results": results, "elapsed": round(elapsed, 2)}

        except Exception as e:
            self._sync_mgr.mark_error("tier2", str(e))
            self.stats["errors"] += 1
            logger.error(f"Tier2 同步失败: {e}")
            return {"status": "error", "error": str(e)}

    # ================================================================
    # Tier 3 — 低频同步 (Daily)
    # ================================================================

    def _tier3_loop(self):
        """Tier 3 后台循环"""
        # 首次启动延迟，等系统稳定
        time.sleep(60)
        while self._running:
            try:
                self.tier3_sync()
            except Exception as e:
                logger.error(f"Tier3 异常: {e}")
                self.stats["errors"] += 1
            # 每小时检查一次是否需要执行
            for _ in range(3600):
                if not self._running:
                    break
                time.sleep(1)

    def tier3_sync(self) -> Dict:
        """
        Tier 3: 低频同步（每日盘前/盘后各一次）
        - 基本面数据
        - 交易日历
        - 公司事件（分红/拆股/财报）
        """
        if not self._tiger.is_connected():
            return {"status": "skipped", "reason": "not_connected"}

        # 检查今天是否已执行
        today = datetime.now().strftime("%Y-%m-%d")
        last_status = self._sync_mgr.get_last_sync("tier3")
        if last_status["last_success_time"] and today in str(last_status["last_success_time"]):
            logger.debug(f"Tier3: 今日已执行，跳过")
            return {"status": "skipped", "reason": "already_done_today"}

        self._sync_mgr.start_sync("tier3")
        start = time.time()
        results = {}

        try:
            all_tickers = settings.DATA_ALL_TICKERS

            # 1. 基本面数据（批量获取，分批）
            if rate_limiter.can_call():
                meta_saved = 0
                for batch_idx in range(0, len(all_tickers), 20):
                    batch = all_tickers[batch_idx:batch_idx + 20]
                    fundamentals = self._tiger.get_stock_fundamentals(batch)
                    if fundamentals:
                        self._store.save_stock_metadata_batch(fundamentals)
                        meta_saved += len(fundamentals)
                    if batch_idx + 20 < len(all_tickers):
                        time.sleep(2)  # 批间延迟
                results["fundamentals"] = meta_saved

            # 2. 交易日历（US市场）
            if rate_limiter.can_call():
                calendar = self._tiger.get_trading_calendar("US")
                if calendar:
                    self._store.save_market_calendar_batch(calendar)
                    results["calendar_US"] = len(calendar)

            # 3. 港股交易日历
            if rate_limiter.can_call():
                calendar_hk = self._tiger.get_trading_calendar("HK")
                if calendar_hk:
                    self._store.save_market_calendar_batch(calendar_hk)
                    results["calendar_HK"] = len(calendar_hk)

            # 4. 公司事件（分红/拆股/财报）
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

            logger.info(f"Tier3 完成: {results} ({elapsed:.1f}s)")

            return {"status": "success", "results": results, "elapsed": round(elapsed, 2)}

        except Exception as e:
            self._sync_mgr.mark_error("tier3", str(e))
            self.stats["errors"] += 1
            logger.error(f"Tier3 同步失败: {e}")
            return {"status": "error", "error": str(e)}

    # ================================================================
    # All-Time — 全量历史拉取
    # ================================================================

    def run_alltime(self, force: bool = False) -> Dict:
        """
        全量历史数据拉取（首次部署或需要完整数据时执行）

        在非交易时段执行，预计 30-45 分钟。

        Args:
            force: 是否强制执行（忽略已有的 last_sync 状态）

        Returns:
            { status, orders, transactions, fundamentals, elapsed }
        """
        if self._alltime_running:
            logger.warning("All-Time 同步已在运行中")
            return {"status": "skipped", "reason": "already_running"}

        if not self._tiger.is_connected():
            logger.error("All-Time: Tiger 未连接")
            return {"status": "error", "reason": "not_connected"}

        # 检查是否需要全量同步
        if not force and not self._sync_mgr.needs_full_sync("alltime", max_age_hours=720):
            logger.info("All-Time: 不需要全量同步（30天内已执行）")
            return {"status": "skipped", "reason": "not_needed"}

        self._alltime_running = True
        self._sync_mgr.start_sync("alltime")
        start = time.time()
        results = {}

        try:
            # 1. 历史订单（分页拉取）
            logger.info("📥 All-Time Phase 1/5: 拉取历史订单...")
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
                logger.info(f"  订单 第{page}页: {len(orders)} 条, 累计 {len(all_orders)}")
                if len(orders) < self.ALLTIME_BATCH_SIZE:
                    break
                time.sleep(self.ALLTIME_DELAY_BETWEEN)

            if all_orders:
                self._store.save_tiger_orders_batch(all_orders)
            results["orders"] = len(all_orders)

            # 2. 成交明细（分页拉取）
            logger.info("📥 All-Time Phase 2/5: 拉取成交明细...")
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
                logger.info(f"  成交 第{page}页: {len(trans)} 条, 累计 {len(all_transactions)}")
                if len(trans) < self.ALLTIME_BATCH_SIZE:
                    break
                time.sleep(self.ALLTIME_DELAY_BETWEEN)

            if all_transactions:
                self._store.save_tiger_transactions_batch(all_transactions)
            results["transactions"] = len(all_transactions)

            # 3. 已成交订单
            logger.info("📥 All-Time Phase 3/5: 拉取已成交订单...")
            filled_orders = self._tiger.get_filled_orders()
            if filled_orders:
                self._store.save_tiger_orders_batch(filled_orders)
                results["filled_orders"] = len(filled_orders)

            # 4. 已取消订单
            logger.info("📥 All-Time Phase 4/5: 拉取已取消订单...")
            cancelled = self._tiger.get_cancelled_orders()
            if cancelled:
                self._store.save_tiger_orders_batch(cancelled)
                results["cancelled_orders"] = len(cancelled)

            # 5. 全部基本面
            logger.info("📥 All-Time Phase 5/5: 拉取全部基本面...")
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
                f"✅ All-Time 完成: {results} ({elapsed:.0f}s = {elapsed/60:.1f}min)"
            )

            return {
                "status": "success",
                "results": results,
                "elapsed": round(elapsed, 2),
            }

        except Exception as e:
            self._sync_mgr.mark_error("alltime", str(e))
            self.stats["errors"] += 1
            logger.error(f"All-Time 同步失败: {e}")
            return {"status": "error", "error": str(e)}

        finally:
            self._alltime_running = False

    # ================================================================
    # 状态 & 统计
    # ================================================================

    def get_status(self) -> Dict:
        """获取服务状态"""
        all_status = self._sync_mgr.get_all_sync_status()
        return {
            "running": self._running,
            "alltime_running": self._alltime_running,
            "rate_limiter": rate_limiter.get_stats(),
            "sync_status": all_status,
            "stats": dict(self.stats),
        }

    def is_syncing(self) -> bool:
        """检查是否有同步正在进行"""
        return self._alltime_running or any(
            self._sync_mgr.is_syncing(t)
            for t in ["tier1", "tier2", "tier3"]
        )
