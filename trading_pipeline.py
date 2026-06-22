"""
Trading Pipeline — v2 核心交易编排器
=====================================
替代 v1 auto_trader.py，串联六微服务执行 T+0 交易周期。

v2.2 重构 (T04):
  • Pre-cycle: 交易日切换 / 市场时段 / Tiger同步 / 熔断 / 杠杆 / 日交易上限
  • 七步主线: Universe → Data → Factors → Inference → Risk → Optimize → Execute
  • Post-cycle: 空头修复 / WS推送 / 状态保存
  • TigerExecutor 统一 live/paper 执行

七步流程:
  0. Get Active Universe — 获取当日活跃股票池
  1. Fetch Market Data — HTTP → data-service:8011
  2. Compute Factors — 本地 FactorEngine
  3. Run Inference — 本地 InferenceEngine
  4. Apply Risk Checks — RiskGate（四道风控）
  5. Optimize Portfolio — HTTP → execution-service:8016 BL optimizer
  6. Execute Rebalance — TigerExecutor (live/paper)
  7. Record Performance — 写入 shared database
"""
import asyncio
import json
import sqlite3
import time
import uuid as _uuid
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

import httpx
import numpy as np
import pandas as pd
from loguru import logger

from configs.pipeline_config import PipelineConfig, pipeline_config
from shared.risk_gate import RiskGate, RiskResult
from shared.signal_to_views import signals_to_bl_views, validate_views
import shared.tiger_bridge as _tiger_bridge

# ── v2 服务模块（已有，不改动） ──────────────────────────────
try:
    from services.factor_service.engine.factor_engine import FactorEngine
except ImportError as e:
    logger.warning(f"FactorEngine import failed ({e}), using stub")
    FactorEngine = None  # type: ignore[assignment]

try:
    from services.model_infer_service.inference_engine import InferenceEngine
except ImportError as e:
    logger.warning(f"InferenceEngine import failed ({e}), using stub")
    InferenceEngine = None  # type: ignore[assignment]

try:
    from services.execution_service.live.circuit_breaker import CircuitBreaker
except ImportError as e:
    logger.warning(f"CircuitBreaker import failed ({e}), using stub")
    CircuitBreaker = None  # type: ignore[assignment]

# ── v2 共享模块 ───────────────────────────────────────────────
from shared.portfolio_manager import PortfolioManager
from shared.risk_manager import RiskManager
from shared.tiger_executor import TigerExecutor
from shared.daily_state import DailyState
from shared.ws_pusher import WsPusher
from shared.market_session import get_market_status, is_any_market_open
from shared.git_sync import git_sync


class TradingPipeline:
    """v2 核心交易编排器。

    七步串联 v2 微服务管线，替代 v1 auto_trader.py。
    每步独立 try/except，单步失败不中断整轮循环。

    Pre-cycle 检查 (P0/P1):
      - 交易日切换 → 重置风控与日初数据
      - 市场时段 → 休市时仅更新估值
      - Tiger 同步 → 全覆盖拉取持仓/现金
      - 组合熔断 → 日亏≥5% 或回撤≥25% 触发平仓
      - 杠杆铁律 → 杠杆≥1.001 阻止所有买入
      - 日交易上限 → 达上限后跳过交易仅更新估值

    Post-cycle 检查:
      - 空头修复 → 检测负持仓自动买回
      - WS 推送 → 每步和周期总结推送到前端
      - 状态保存 → portfolio/risk 状态持久化
    """

    def __init__(self, config: PipelineConfig) -> None:
        self.config: PipelineConfig = config
        self.service_urls: Dict[str, str] = config.SERVICE_BASE_URLS
        self.logger = logger  # alias for readability

        # ── 本地引擎（v2 已有，导入失败时降级为 stub） ──────
        logger.info("初始化本地引擎...")
        if FactorEngine is not None:
            self.factor_engine: FactorEngine = FactorEngine()
            self.factor_engine.register_all()
            logger.info(f"  ✅ FactorEngine 已就绪 ({len(self.factor_engine.factors)} factors)")
        else:
            self.factor_engine = None  # type: ignore[assignment]
            logger.warning("  ⚠️ FactorEngine 不可用 — stub 模式")

        if InferenceEngine is not None:
            self.inference_engine: InferenceEngine = InferenceEngine()
            load_status = self.inference_engine.load_models()
            loaded_count = sum(1 for v in load_status.values() if v)
            logger.info(f"  ✅ InferenceEngine 已就绪 ({loaded_count}/{len(load_status)} models loaded)")
        else:
            self.inference_engine = None  # type: ignore[assignment]
            logger.warning("  ⚠️ InferenceEngine 不可用 — stub 模式")

        # ── 风控组件 ─────────────────────────────────────────
        logger.info("初始化风控组件...")
        if CircuitBreaker is not None:
            self.circuit_breaker: CircuitBreaker = CircuitBreaker()
            logger.info("  ✅ CircuitBreaker 已就绪")
        else:
            self.circuit_breaker = None  # type: ignore[assignment]
            logger.warning("  ⚠️ CircuitBreaker 不可用 — stub 模式")
        self.risk_gate: RiskGate = RiskGate(
            circuit_breaker=self.circuit_breaker,
            risk_service_url=self.service_urls["risk"],
            constraints={
                "barra_exposure_max_z": config.BARRA_EXPOSURE_MAX_Z,
                "var_limit_pct": config.VAR_LIMIT_PCT,
                "cvar_limit_pct": config.CVAR_LIMIT_PCT,
            },
        )
        logger.info("  ✅ RiskGate (四道风控) 已就绪")

        # ── 组合管理 ─────────────────────────────────────────
        logger.info("初始化组合管理器...")
        self.portfolio: PortfolioManager = PortfolioManager(
            initial_capital=100000.0,
        )
        # 尝试加载已有状态
        self.portfolio.load_state("data/portfolio_state.json")
        logger.info(
            f"  ✅ PortfolioManager 已就绪 "
            f"(现金 ${self.portfolio.cash:,.2f}, "
            f"持仓 {len(self.portfolio.positions)} 只)"
        )

        # ── 风控管理器 (v2) ──────────────────────────────────
        logger.info("初始化风控管理器 (v2)...")
        self.risk_manager: RiskManager = RiskManager(
            initial_capital=self.portfolio.initial_capital,
            breaker_mode="hard",
            max_daily_trades=config.MAX_DAILY_TRADES,
        )
        self.risk_manager.sync_portfolio_value(
            self.portfolio.total_value,
            self.portfolio.cash,
        )
        logger.info("  ✅ RiskManager (v2) 已就绪")

        # ── 每日状态追踪 ─────────────────────────────────────
        self.daily_state: DailyState = DailyState(
            daily_start_value=self.portfolio.total_value,
        )
        logger.info("  ✅ DailyState 已就绪")

        # ── Tiger 连接 ───────────────────────────────────────
        logger.info("初始化 Tiger 连接...")
        self.tiger = _tiger_bridge
        self.tiger_ready: bool = self.tiger.connect()
        if self.tiger_ready:
            logger.info("  ✅ Tiger Broker 已连接")
        else:
            logger.warning("  ⚠️ Tiger Broker 未连接 — Paper Trading 模式")

        # ── 执行器 ───────────────────────────────────────────
        logger.info("初始化 TigerExecutor...")
        self.executor: TigerExecutor = TigerExecutor(
            mode="live" if (self.tiger_ready and self.config.EXECUTION_MODE == "live") else "paper",
            portfolio=self.portfolio,
            risk=self.risk_manager,
            tiger_bridge=self.tiger,
        )
        logger.info(f"  ✅ TigerExecutor 已就绪 (mode={self.executor.mode})")

        # ── WebSocket 推送器 ─────────────────────────────────
        api_base: str = self.service_urls.get("api", "")
        self.ws_pusher: WsPusher = WsPusher(
            api_url=api_base,
            enabled=config.ENABLE_WS_PUSH,
        )
        if config.ENABLE_WS_PUSH:
            logger.info("  ✅ WsPusher 已启用")
        else:
            logger.info("  ⚠️ WsPusher 已禁用 (ENABLE_WS_PUSH=False)")

        # ── 数据目录 ─────────────────────────────────────────
        self.data_dir: Path = Path("data/daily")
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # ── HTTP 客户端 ──────────────────────────────────────
        self._http: Optional[httpx.AsyncClient] = None

        # ── 状态 ────────────────────────────────────────────
        self.cycle_count: int = 0
        self.trades_today: int = 0
        self.trade_date: str = datetime.now().strftime("%Y-%m-%d")
        self._market_round_index: int = 0

        logger.info("=" * 60)
        logger.info("TradingPipeline 初始化完成")
        logger.info("=" * 60)

    async def _get_http(self) -> httpx.AsyncClient:
        """Lazy init httpx client."""
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.HTTP_TIMEOUT),
            )
        return self._http

    async def close(self) -> None:
        """Clean up resources."""
        if self._http is not None:
            await self._http.aclose()
            self._http = None
        await self.risk_gate.close()
        await self.ws_pusher.close()

    # ═══════════════════════════════════════════════════════════════
    # Main Loop
    # ═══════════════════════════════════════════════════════════════

    async def run(self, interval_seconds: int = 300) -> None:
        """主循环：每隔 interval_seconds 秒运行一个交易周期。

        Args:
            interval_seconds: 循环间隔，默认 300s (5 min)
        """
        logger.info(f"🚀 交易管线启动 — 间隔 {interval_seconds}s")

        # ── P2-3: 强制卖出指定持仓 ──────────────────────────
        if self.config.FORCE_SELL_TICKERS:
            try:
                self._execute_force_sells()
            except Exception as exc:
                logger.error(f"强制清仓异常 (非致命): {exc}")

        try:
            while True:
                try:
                    await self.run_cycle()
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    logger.exception(f"❌ Cycle #{self.cycle_count} 异常: {e}")
                    retry_wait: int = 60
                    logger.info(f"休眠 {retry_wait}s 后重试...")
                    await asyncio.sleep(retry_wait)
                    continue

                # ── P2-1: Git 自动同步 (每6周期) ────────────
                if (
                    self.config.GIT_AUTO_SYNC
                    and self.cycle_count > 0
                    and self.cycle_count % 6 == 0
                ):
                    try:
                        self._git_sync()
                    except Exception as exc:
                        logger.debug(f"Git 同步异常 (静默): {exc}")

                logger.info(f"休眠 {interval_seconds // 60} 分钟...")
                await asyncio.sleep(interval_seconds)
        finally:
            await self.close()

    async def run_cycle(self) -> Optional[Dict]:
        """执行一次完整的 T+0 交易周期。

        Returns:
            dict with cycle summary or None on early abort.
        """
        self.cycle_count += 1
        t_start: float = time.time()

        logger.info(
            f"\n{'=' * 50}\n"
            f"  Cycle #{self.cycle_count} — {datetime.now().strftime('%H:%M:%S')}\n"
            f"{'=' * 50}"
        )

        # ═══════════════════════════════════════════════════════════
        # Pre-cycle 检查
        # ═══════════════════════════════════════════════════════════

        # ── 1. 交易日切换检测 ────────────────────────────────
        if self.daily_state.check_date_roll():
            self.risk_manager.reset_daily_state()
            self.daily_state.reset_for_new_day(self.portfolio.total_value)
            self.trades_today = 0
            self.trade_date = self.daily_state.trade_date

        # ── 2. P0-3: 市场时段检查 ────────────────────────────
        if self.config.TRADING_HOURS_ONLY:
            try:
                if not is_any_market_open():
                    logger.info("📴 所有市场休市，跳过交易 — 仅更新估值")
                    prices = await self._get_live_prices()
                    self.portfolio.update_value(prices)
                    await self._push_step_update(0, {
                        "status": "markets_closed",
                        "portfolio": self.portfolio.get_metrics(),
                    })
                    return None
            except Exception as e:
                logger.warning(f"市场时段检查异常: {e}，继续执行")

        # ── 3. P0-4, P0-5: Tiger 状态同步 ────────────────────
        if self.tiger_ready:
            try:
                sync_result = self.portfolio.sync_from_tiger(self.tiger, force=False)
                if sync_result.get("synced"):
                    self.risk_manager.sync_portfolio_value(
                        self.portfolio.total_value,
                        self.portfolio.cash,
                    )
                    logger.info(
                        f"🔄 Tiger 同步: {sync_result.get('positions')} 只持仓, "
                        f"现金 ${sync_result.get('cash', 0):,.2f}"
                    )
            except Exception as e:
                logger.warning(f"Tiger 同步异常（继续使用本地数据）: {e}")

        # ── 4. P0-2: 组合熔断检查 ────────────────────────────
        try:
            prices = await self._get_live_prices()
            self.portfolio.update_value(prices)
        except Exception:
            prices = {}

        report = self.risk_manager.check_circuit_breaker()
        if report.circuit_breaker and self.risk_manager.breaker_mode == "hard":
            logger.error(f"🚨 熔断触发: {report.reason}")
            await self.ws_pusher.push_alert("circuit_breaker", report.reason)
            # P1-2: Tiger price fallback when HTTP prices are empty
            if not prices and self.tiger_ready:
                try:
                    for ticker in list(self.portfolio.positions.keys()):
                        quote = self.tiger.get_quote(ticker)
                        if quote and quote.get("last", 0) > 0:
                            prices[ticker] = float(quote["last"])
                except Exception:
                    pass
            self.risk_manager.liquidate_all(prices, self.tiger)
            await self._push_step_update(-1, {
                "circuit_breaker": True,
                "reason": report.reason,
            })
            return None

        # ── 5. P1-1: 杠杆检查 ────────────────────────────────
        leverage_blocked: bool = False
        if self.tiger_ready:
            try:
                acct = self.tiger.get_account_info()
                if acct and self.risk_manager.check_leverage(acct):
                    logger.warning("🚫 杠杆铁律: 阻止所有买入")
                    await self.ws_pusher.push_alert(
                        "leverage",
                        f"Tiger 杠杆率 {acct.get('leverage', '?')} ≥ 1.001 — 阻止所有买入",
                    )
                    leverage_blocked = True
            except Exception as e:
                logger.warning(f"杠杆检查异常: {e}")

        # ── P0-3: 杠杆阻止买入 ────────────────────────────────
        if leverage_blocked:
            logger.error("🚫 Tiger 账户杠杆率过高 — 跳过所有买入")
            return None

        # ── 6. P1-2: 每日交易上限 ────────────────────────────
        if self.risk_manager.check_daily_limit():
            logger.info(
                f"📊 日交易上限已达 ({self.risk_manager.trades_today}/"
                f"{self.risk_manager.max_daily_trades})，仅更新估值"
            )
            self.portfolio.update_value(prices)
            await self._push_step_update(0, {
                "status": "daily_limit_reached",
                "trades_today": self.risk_manager.trades_today,
                "max_daily_trades": self.risk_manager.max_daily_trades,
            })
            return None

        # ═══════════════════════════════════════════════════════════
        # Main Pipeline (7 Steps)
        # ═══════════════════════════════════════════════════════════

        # Step 0: Get Active Universe
        tickers: List[str] = await self._get_active_universe()
        if not tickers:
            logger.warning("活跃股票池为空，跳过本轮")
            return None
        logger.info(f"Step 0: 股票池 {len(tickers)} 只")
        await self._push_step_update(0, {"tickers": len(tickers)})

        # Step 1: Fetch Market Data
        data: Dict = await self._fetch_market_data(tickers)
        if not data or len(data) < 2:
            logger.warning("市场数据不足，跳过本轮")
            return None
        await self._push_step_update(1, {"symbols_fetched": len(data)})

        # Step 2: Compute Factors
        factor_df = await self._compute_factors(data)
        n_factors: int = factor_df.shape[1] - 1 if factor_df.shape[1] > 1 else 0
        await self._push_step_update(2, {
            "tickers_processed": len(factor_df),
            "factors": n_factors,
        })

        # Step 3: Run Inference
        signals: List[Dict] = await self._run_inference(factor_df, tickers)
        if not signals:
            logger.warning("无有效信号，跳过本轮")
            return None
        await self._push_step_update(3, {"raw_signals": len(signals)})

        # ── DB Write: 保存信号到 signals 表 ──────────────────────
        self._write_signals_to_db(signals)

        # Step 4: Apply Risk Checks
        approved: List[Dict] = await self._apply_risk_checks(signals)
        await self._push_step_update(4, {
            "approved": len(approved),
            "rejected": len(signals) - len(approved),
        })

        # Step 5: Optimize Portfolio
        target_weights: Dict = await self._optimize_portfolio(approved)
        await self._push_step_update(5, {
            "target_positions": len(target_weights),
        })

        # Step 6: Execute Rebalance — TigerExecutor
        orders: List[Dict] = await self._execute_rebalance(target_weights)

        # ── DB Write: 保存交易到 trades 表 ──────────────────────
        self._write_trades_to_db(orders)
        await self._push_step_update(6, {
            "orders": len(orders),
            "trades_today": self.trades_today,
        })

        # Step 7: Record Performance
        await self._record_performance(orders)

        # ═══════════════════════════════════════════════════════════
        # Post-cycle 检查
        # ═══════════════════════════════════════════════════════════

        # ── 7. P1-3: 空头修复 ────────────────────────────────
        try:
            if not prices:
                prices = await self._get_live_prices()
            fixed: int = self.risk_manager.fix_short_positions(
                self.portfolio, self.tiger, prices,
            )
            if fixed:
                logger.info(f"🔧 空头修复: {fixed} 只")
        except Exception as e:
            logger.warning(f"空头修复异常: {e}")

        # ── 8. 状态保存 ──────────────────────────────────────
        try:
            self.portfolio.save_state()
        except Exception as e:
            logger.warning(f"状态保存异常: {e}")

        # ── P2-2: Tiger 全量同步到本地 DB (每10轮) ──────────
        if self.tiger_ready and self.cycle_count % 10 == 0:
            try:
                self.tiger.sync_all_to_db()
                logger.debug(f"Tiger 全量同步完成 (cycle #{self.cycle_count})")
            except Exception:
                pass  # 静默降级，不阻塞交易

        # ── 周期汇总 ─────────────────────────────────────────
        elapsed: float = time.time() - t_start
        logger.info(
            f"⏱  Cycle #{self.cycle_count} 完成 "
            f"| 耗时 {elapsed:.1f}s "
            f"| 信号 {len(signals)} → 通过 {len(approved)} → 订单 {len(orders)}"
        )

        cycle_summary = {
            "cycle": self.cycle_count,
            "timestamp": datetime.now().isoformat(),
            "tickers": len(tickers),
            "signals": len(signals),
            "approved": len(approved),
            "orders": len(orders),
            "elapsed_seconds": round(elapsed, 2),
        }

        # ── P1-5: WS 推送周期总结 ────────────────────────────
        await self.ws_pusher.push_summary(self.cycle_count, cycle_summary)

        return cycle_summary

    # ═══════════════════════════════════════════════════════════════
    # Step 0: Get Active Universe
    # ═══════════════════════════════════════════════════════════════

    async def _get_active_universe(self) -> List[str]:
        """获取当日活跃股票池。

        Returns:
            List of ticker strings, capped at MAX_TICKERS_PER_CYCLE.
        """
        t0: float = time.time()
        tickers: List[str] = []
        try:
            # v2: 从 data-service 获取股票池 (带重试)
            data = await self._retry_http_call(
                "GET",
                f"{self.service_urls['data']}/api/v2/data/universe",
                params={"active": "true"},
            )
            if data is not None:
                symbols_data = data.get("data", data)
                if isinstance(symbols_data, dict) and "stocks" in symbols_data:
                    tickers = [s["ticker"] for s in symbols_data["stocks"] if s.get("ticker")]
                elif isinstance(symbols_data, list):
                    tickers = [
                        (s.get("symbol") or s.get("ticker") or "")
                        for s in symbols_data
                    ]
                elif isinstance(symbols_data, dict):
                    tickers = list(symbols_data.keys())
            else:
                tickers = []
        except Exception as e:
            logger.warning(f"获取股票池失败: {e}，使用 v1 fallback")
            tickers = self._get_active_universe_v1_fallback()

        # 过滤并限制数量
        tickers = [t for t in tickers if isinstance(t, str) and t]

        # ── 市场轮询：每轮只分析一个市场 ──
        if self.config.MARKET_ROUND_ROBIN and self.config.MARKET_ROTATION:
            target_market = self.config.MARKET_ROTATION[
                self._market_round_index % len(self.config.MARKET_ROTATION)
            ]
            if target_market == "HK":
                tickers = [t for t in tickers if ".HK" in t]
            elif target_market == "US":
                tickers = [t for t in tickers if ".HK" not in t and ".SI" not in t and ".AX" not in t and ".NZ" not in t and ".SH" not in t and ".SZ" not in t]
            elif target_market == "SG":
                tickers = [t for t in tickers if ".SI" in t]
            elif target_market == "AU":
                tickers = [t for t in tickers if ".AX" in t]
            elif target_market == "NZ":
                tickers = [t for t in tickers if ".NZ" in t]
            elif target_market == "CN":
                tickers = [t for t in tickers if ".SH" in t or ".SZ" in t]
            tickers = tickers[: self.config.MAX_STOCKS_PER_MARKET]
            logger.info(f"  🎯 市场轮询: {target_market}, {len(tickers)} 只")
            self._market_round_index += 1

        tickers = tickers[: self.config.MAX_TICKERS_PER_CYCLE]

        elapsed: float = time.time() - t0
        logger.info(f"  Step 0 完成 ({elapsed:.1f}s): {len(tickers)} 只")
        return tickers

    def _get_active_universe_v1_fallback(self) -> List[str]:
        """v1 fallback: 从 backend 股票池获取。"""
        try:
            from backend.data_engine.stock_universe import stock_universe
            return stock_universe.all_tickers
        except Exception:
            pass
        # Hardcoded minimal fallback
        return ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]

    # ═══════════════════════════════════════════════════════════════
    # Step 1: Fetch Market Data
    # ═══════════════════════════════════════════════════════════════

    async def _fetch_market_data(self, tickers: List[str]) -> Dict:
        """获取市场数据 (v1 fallback + ParquetStore 同步)。

        使用 v1 MarketDataEngine 获取数据，同时写入 ParquetStore 供
        v2 InferenceEngine 读取。
        """
        result = self._fetch_market_data_v1_fallback(tickers)

        # 同步写入 ParquetStore 供 v2 inference engine 使用
        if result:
            try:
                from services.data_service.storage.parquet_store import ParquetStore
                store = ParquetStore()
                for ticker, d in result.items():
                    if isinstance(d, dict) and "features" in d:
                        features = d["features"]
                        if isinstance(features, np.ndarray) and features.ndim == 2:
                            df = pd.DataFrame(features)
                            df["close"] = d.get("close", 0.0)
                            try:
                                store.write_daily(ticker, df)
                            except Exception:
                                pass
            except Exception:
                pass

        return result

    def _fetch_market_data_v1_fallback(self, tickers: List[str]) -> Dict:
        """v1 fallback: 使用 backend MarketDataEngine。"""
        try:
            from backend.data_engine import MarketDataEngine
            from backend.data_engine.data_pipeline import DataPipeline

            engine = MarketDataEngine()
            pipeline = DataPipeline()
            data_dict: Dict = {}
            errors: int = 0

            for ticker in tickers:
                try:
                    df = engine.get_historical_data(ticker, period="2y", interval="1d")
                    if df is not None and not df.empty:
                        processed = pipeline.process(df)
                        if processed is not None:
                            fcols = [
                                c for c in pipeline.FEATURE_COLUMNS
                                if c in processed.columns
                            ]
                            if len(fcols) >= 30:
                                data_dict[ticker] = {
                                    "features": processed[fcols].values,
                                    "close": (
                                        float(df["Close"].iloc[-1])
                                        if "Close" in df.columns
                                        else float(processed.iloc[-1, 0])
                                    ),
                                }
                    else:
                        errors += 1
                except Exception:
                    errors += 1

            logger.info(f"  Step 1 fallback: {len(data_dict)}/{len(tickers)} 成功, {errors} 失败")
            return data_dict
        except Exception as e:
            logger.error(f"Step 1 fallback 也失败: {e}")
            return {}

    # ═══════════════════════════════════════════════════════════════
    # Step 2: Compute Factors
    # ═══════════════════════════════════════════════════════════════

    async def _compute_factors(self, data: Dict):
        """本地 FactorEngine 计算因子。

        Args:
            data: {ticker: {features: ndarray, close: float}, ...}

        Returns:
            DataFrame with factor values indexed by ticker.
        """
        t0: float = time.time()
        if self.factor_engine is None or not data:
            logger.warning("  Step 2: FactorEngine stub — returning empty DataFrame")
            return pd.DataFrame({"ticker": list(data.keys())})

        try:
            # Convert v1 fallback format → DataFrame dict for FactorEngine
            dfs: dict = {}
            for ticker, d in data.items():
                if isinstance(d, dict) and "features" in d:
                    features = d["features"]
                    if isinstance(features, np.ndarray) and features.ndim == 2:
                        n_cols = features.shape[1]
                        cols = [f"f{i}" for i in range(n_cols)]
                        dfs[ticker] = pd.DataFrame(features, columns=cols)
                    elif isinstance(features, np.ndarray):
                        dfs[ticker] = pd.DataFrame({"f0": features})
                    else:
                        dfs[ticker] = pd.DataFrame({"close": [d.get("close", 0)]})
                elif isinstance(d, pd.DataFrame):
                    dfs[ticker] = d
                else:
                    dfs[ticker] = pd.DataFrame({"close": [0.0]})

            factor_results = self.factor_engine.compute_all_multi(dfs)
            rows = []
            for ticker, fdf in factor_results.items():
                if fdf is not None and not fdf.empty:
                    row = {"ticker": str(ticker)}
                    for col in fdf.columns[:68]:
                        try:
                            row[col] = float(fdf[col].iloc[-1])
                        except (IndexError, ValueError):
                            row[col] = 0.0
                    rows.append(row)
                else:
                    rows.append({"ticker": str(ticker)})

            factor_df = pd.DataFrame(rows)
            elapsed: float = time.time() - t0
            n_tickers: int = len(factor_df)
            n_factors: int = factor_df.shape[1] - 1 if factor_df.shape[1] > 1 else 0
            logger.info(f"  Step 2 ({elapsed:.1f}s): {n_tickers} tickers × {n_factors} factors")
            return factor_df
        except Exception as e:
            logger.error(f"Step 2 因子计算失败: {e}", exc_info=True)
            return pd.DataFrame({"ticker": list(data.keys())})

    # ═══════════════════════════════════════════════════════════════
    # Step 3: Run Inference
    # ═══════════════════════════════════════════════════════════════

    async def _run_inference(self, factor_df, tickers: List[str]) -> List[Dict]:
        """本地 InferenceEngine 模型推理 — Top-N 信号选择。

        Args:
            factor_df: Factor DataFrame from Step 2 (must have 'ticker' column).
            tickers: Active ticker list.

        Returns:
            Top-N signal dicts by |signal| descending.
        """
        t0: float = time.time()
        if self.inference_engine is None or factor_df is None or factor_df.empty:
            logger.warning("  Step 3: InferenceEngine stub — returning HOLD for all tickers")
            return []

        try:
            # Filter to tickers with available data in ParquetStore
            try:
                from services.data_service.storage.parquet_store import ParquetStore
                store = ParquetStore()
                available_tickers = store.list_tickers() or []
                if available_tickers:
                    tickers_with_data = [t for t in tickers if t in available_tickers]
                    if len(tickers_with_data) < len(tickers):
                        logger.info(
                            f"  Step 3: {len(tickers_with_data)}/{len(tickers)} tickers have data "
                            f"(filtered {len(tickers) - len(tickers_with_data)} without)"
                        )
                    tickers = tickers_with_data
            except Exception:
                pass  # If store unavailable, try all tickers

            if not tickers:
                logger.warning("  Step 3: 无有数据的 ticker，跳过推理")
                return []

            # Ensure factor_df has a 'ticker' column for batch inference
            if "ticker" not in factor_df.columns and len(factor_df) <= len(tickers):
                factor_df = factor_df.copy()
                factor_df["ticker"] = tickers[:len(factor_df)]

            signals: List[Dict] = self.inference_engine.generate_signals_batch(
                factor_df,
                top_n=self.config.TOP_N_SIGNALS,
                min_threshold=self.config.SIGNAL_THRESHOLD_MIN,
                min_confidence=self.config.MIN_CONFIDENCE,
            )

            elapsed: float = time.time() - t0
            logger.info(
                f"  Step 3 ({elapsed:.1f}s): {len(signals)} signals "
                f"(top {self.config.TOP_N_SIGNALS} by |score|, "
                f"floor={self.config.SIGNAL_THRESHOLD_MIN}, "
                f"min_conf={self.config.MIN_CONFIDENCE})"
            )
            return signals
        except Exception as e:
            logger.error(f"Step 3 推理失败: {e}", exc_info=True)
            return []

    # ═══════════════════════════════════════════════════════════════
    # Step 4: Apply Risk Checks
    # ═══════════════════════════════════════════════════════════════

    async def _apply_risk_checks(self, signals: List[Dict]) -> List[Dict]:
        """RiskGate 四道风控检查。

        逐个信号通过风险关卡，不通过的记录原因并跳过。

        Args:
            signals: List of signal dicts.

        Returns:
            Filtered list of signals that passed all risk checks.
        """
        t0: float = time.time()
        if not self.config.ENABLE_RISK_CHECKS:
            logger.info("  Step 4: 风控已禁用 (ENABLE_RISK_CHECKS=False)")
            return signals

        approved: List[Dict] = []
        rejected: List[str] = []
        portfolio_state: Dict = {
            "total_value": self.portfolio.total_value,
            "cash": self.portfolio.cash,
            "positions": dict(self.portfolio.positions),
        }

        for sig in signals:
            ticker: str = sig.get("ticker", "")
            signal_strength: float = sig.get("signal", sig.get("strength", 0.0))
            confidence: float = sig.get("confidence", 0.5)
            price: float = sig.get("price", sig.get("close", 0.0))

            # 估算 quantity（基于信号强度和组合现金）
            if price <= 0:
                rejected.append(f"{ticker}: invalid price")
                continue

            quantity: int = int(
                self.portfolio.cash
                * min(abs(signal_strength), 0.20)
                / price
            )
            if quantity < 1:
                quantity = 1

            result: RiskResult = await self.risk_gate.check(
                ticker=ticker,
                quantity=quantity,
                price=price,
                portfolio_state=portfolio_state,
                signal_strength=signal_strength,
            )

            if result.passed:
                approved.append(sig)
            else:
                rejected.append(f"{ticker}: {result.reason}")
                if result.warnings:
                    for w in result.warnings:
                        logger.debug(f"    ⚠️ {ticker}: {w}")

        elapsed: float = time.time() - t0
        logger.info(
            f"  Step 4 ({elapsed:.1f}s): {len(approved)} 通过 / "
            f"{len(rejected)} 拒绝 / {len(signals)} 总计"
        )
        if rejected:
            logger.info(f"    拒绝详情: {rejected[:5]}{'...' if len(rejected) > 5 else ''}")

        return approved

    # ═══════════════════════════════════════════════════════════════
    # Step 5: Optimize Portfolio
    # ═══════════════════════════════════════════════════════════════

    async def _optimize_portfolio(self, signals: List[Dict]) -> Dict[str, float]:
        """HTTP → execution-service:8016 Black-Litterman 组合优化。

        POST /api/v2/execution/optimizer/bl
        Body: {"views": [...], "constraints": {...}}

        Args:
            signals: Approved signal list from Step 4.

        Returns:
            {ticker: target_weight, ...}
        """
        t0: float = time.time()
        if not self.config.ENABLE_PORTFOLIO_OPT:
            logger.info("  Step 5: 组合优化已禁用 — 使用等权分配")
            return self._equal_weight_fallback(signals)

        try:
            # 信号 → BL views
            views: List[Dict] = signals_to_bl_views(signals)
            views = validate_views(views)

            if not views:
                logger.warning("Step 5: 无有效 BL views")
                return {}

            http = await self._get_http()
            payload: Dict = {
                "views": views,
                "constraints": {
                    "max_position_size": 0.20,
                    "min_position_size": 0.0,
                    "max_turnover": 0.30,
                },
            }
            resp = await http.post(
                f"{self.service_urls['execution']}/api/v2/execution/optimizer/bl",
                json=payload,
            )

            if resp.status_code != 200:
                logger.warning(
                    f"BL optimizer 返回 {resp.status_code}: {resp.text[:200]}"
                )
                return self._equal_weight_fallback(signals)

            data = resp.json()
            result_data = data.get("data", data)
            weights: Dict[str, float] = {}

            if isinstance(result_data, dict):
                w = result_data.get("weights", result_data.get("target_holdings", {}))
                if isinstance(w, dict):
                    weights = {str(k): float(v) for k, v in w.items()}
                elif isinstance(w, list):
                    for entry in w:
                        if isinstance(entry, dict):
                            t = entry.get("ticker", "")
                            wt = entry.get("weight", entry.get("target", 0.0))
                            if t:
                                weights[str(t)] = float(wt)

            elapsed: float = time.time() - t0
            logger.info(
                f"  Step 5 ({elapsed:.1f}s): {len(views)} views → "
                f"{len(weights)} target weights"
            )
            return weights

        except httpx.TimeoutException:
            logger.warning("Step 5 BL optimizer 超时 — 使用等权 fallback")
            return self._equal_weight_fallback(signals)
        except Exception as e:
            logger.error(f"Step 5 失败: {e}")
            return self._equal_weight_fallback(signals)

    def _equal_weight_fallback(self, signals: List[Dict]) -> Dict[str, float]:
        """等权分配 fallback — 当组合优化不可用时。"""
        if not signals:
            return {}
        n: int = len(signals)
        weight: float = round(0.20 / max(n, 1), 6)  # cap total at 20%
        return {s.get("ticker", ""): weight for s in signals if s.get("ticker")}

    # ═══════════════════════════════════════════════════════════════
    # Step 6: Execute Rebalance
    # ═══════════════════════════════════════════════════════════════

    async def _execute_rebalance(self, target_weights: Dict[str, float]) -> List[Dict]:
        """TigerExecutor 统一再平衡执行。

        使用 v2 TigerExecutor (live/paper 策略模式) 执行权重调整。
        替代 v1 的 PaperExecutor 手动循环。

        Args:
            target_weights: {ticker: target_weight, ...} from Step 5.

        Returns:
            List of executed order records.
        """
        t0: float = time.time()
        if not target_weights:
            logger.info("  Step 6: 无目标权重，跳过执行")
            return []

        try:
            # 获取实时价格
            prices: Dict[str, float] = {}
            for ticker in target_weights:
                try:
                    http = await self._get_http()
                    resp = await http.get(
                        f"{self.service_urls['data']}/api/v2/data/realtime/{ticker}"
                    )
                    if resp.status_code == 200:
                        rt = resp.json()
                        rt_data = rt.get("data", rt)
                        px = float(rt_data.get("price", rt_data.get("close", 0.0)))
                        if px > 0:
                            prices[ticker] = px
                except Exception:
                    pass

            if not prices:
                logger.warning("Step 6: 无有效价格，跳过执行")
                return []

            # Delegate to TigerExecutor.execute_rebalance
            current_positions: Dict[str, float] = dict(self.portfolio.positions)
            orders: List[Dict] = self.executor.execute_rebalance(
                target_weights=target_weights,
                prices=prices,
                current_positions=current_positions,
            )

            # Count non-rejected trades
            filled: int = sum(1 for o in orders if not o.get("rejected"))
            self.trades_today += filled

            elapsed: float = time.time() - t0
            rejected: int = len(orders) - filled
            logger.info(
                f"  Step 6 ({elapsed:.1f}s): {filled} 笔成交"
                + (f", {rejected} 笔拒绝" if rejected else "")
            )

            # 状态保存
            if orders:
                self.portfolio.save_state()

            return orders

        except Exception as e:
            logger.error(f"Step 6 执行失败: {e}")
            return []

    # ═══════════════════════════════════════════════════════════════
    # Step 7: Record Performance
    # ═══════════════════════════════════════════════════════════════

    async def _record_performance(self, orders: List[Dict]) -> None:
        """绩效记录 — 写入 cache/cycle_history.jsonl + 可选 PostgreSQL。

        Args:
            orders: Executed orders from Step 6.
        """
        t0: float = time.time()
        try:
            metrics: Dict = self.portfolio.get_metrics()

            logger.info(
                f"  Step 7 ({time.time() - t0:.1f}s): "
                f"总资产 ${metrics.get('total_value', 0):,.0f} | "
                f"盈亏 {metrics.get('total_return_pct', 0):+.1f}% | "
                f"持仓 {metrics.get('num_positions', 0)} 只"
            )

            # ── CycleSummary 持久化到 cache/cycle_history.jsonl（追加模式）──
            cycle_summary = {
                "cycle": self.cycle_count,
                "timestamp": datetime.now().isoformat(),
                "trade_date": self.trade_date,
                "orders": len(orders),
                "trades_today": self.trades_today,
                "total_value": metrics.get("total_value", 0),
                "total_return_pct": metrics.get("total_return_pct", 0),
                "num_positions": metrics.get("num_positions", 0),
                "order_ids": [o.get("order_id", "") for o in orders if o.get("order_id")],
            }
            try:
                cache_dir = Path("cache")
                cache_dir.mkdir(parents=True, exist_ok=True)
                history_path = cache_dir / "cycle_history.jsonl"
                with open(history_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(cycle_summary, ensure_ascii=False) + "\n")
                logger.debug(f"Cycle summary appended to {history_path}")
            except Exception as e:
                logger.warning(f"Failed to write cycle_history.jsonl: {e}")

            # ── PostgreSQL 写入（optional，try/except 包裹）──
            try:
                from shared.database import SessionLocal
                from shared.database.models import CyclePerformance

                db = SessionLocal()
                try:
                    record = CyclePerformance(
                        cycle=self.cycle_count,
                        trade_date=self.trade_date,
                        order_count=len(orders),
                        trades_today=self.trades_today,
                        total_value=metrics.get("total_value", 0),
                        total_return_pct=metrics.get("total_return_pct", 0),
                        num_positions=metrics.get("num_positions", 0),
                        created_at=datetime.utcnow(),
                    )
                    db.add(record)
                    db.commit()
                    logger.debug(f"Cycle #{self.cycle_count} written to PostgreSQL")
                except Exception as e:
                    db.rollback()
                    logger.debug(f"PostgreSQL write skipped: {e}")
                finally:
                    db.close()
            except ImportError:
                logger.debug("PostgreSQL not configured — skipping DB write")
            except Exception as e:
                logger.debug(f"PostgreSQL write failed (non-critical): {e}")

        except Exception as e:
            logger.error(f"Step 7 绩效记录异常: {e}")

    # ═══════════════════════════════════════════════════════════════
    # DB Write Helpers — 将信号/交易写入 SQLite 数据库
    # ═══════════════════════════════════════════════════════════════

    def _get_db_path(self) -> Path:
        """Resolve the SQLite database path from backend config."""
        try:
            from configs.settings import settings
            return settings.DB_PATH
        except ImportError:
            return Path("data/quant_trader.db")

    def _write_signals_to_db(self, signals: List[Dict]) -> int:
        """Write trading signals to the ``signals`` table.

        Uses the v2 SQLAlchemy schema (ticker, signal_date, horizon,
        direction, strength, target_weight, predicted_return, confidence,
        risk_score, is_executed).

        Args:
            signals: List of signal dicts from Step 3.

        Returns:
            Number of signals written.
        """
        if not signals:
            return 0

        db_path = self._get_db_path()
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")

        written: int = 0
        today: str = date.today().isoformat()
        now: str = datetime.now().isoformat()

        try:
            for sig in signals:
                ticker: str = sig.get("ticker", "")
                if not ticker:
                    continue

                strength: float = float(sig.get("signal", sig.get("strength", 0.0)))
                direction: int = 1 if strength > 0 else (-1 if strength < 0 else 0)
                confidence: float = float(sig.get("confidence", 0.5))
                predicted_return: float = float(sig.get("predicted_return", strength * 0.01))
                target_weight: float = float(
                    sig.get("target_weight", min(abs(strength) * 0.10, 0.20))
                )
                risk_score: float = float(sig.get("risk_score", 0.0))
                horizon: str = str(sig.get("horizon", "1d"))
                is_executed: bool = bool(sig.get("is_executed", False))

                conn.execute(
                    """INSERT OR REPLACE INTO signals
                       (id, ticker, signal_date, horizon, direction, strength,
                        target_weight, predicted_return, confidence, risk_score,
                        is_executed, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(_uuid.uuid4()),
                        ticker,
                        today,
                        horizon,
                        direction,
                        round(strength, 6),
                        round(target_weight, 6),
                        round(predicted_return, 6),
                        round(confidence, 4),
                        round(risk_score, 4),
                        int(is_executed),
                        now,
                        now,
                    ),
                )
                written += 1

            conn.commit()
            logger.debug(f"  📊 signals → DB: {written} 条写入 signals 表")
        except Exception as e:
            logger.warning(f"signals DB write failed (non-critical): {e}")
        finally:
            conn.close()

        return written

    def _write_trades_to_db(self, orders: List[Dict]) -> int:
        """Write executed orders to the ``trades`` table.

        Uses the v2 SQLAlchemy schema (ticker, trade_date, trade_time,
        side, quantity, price, commission, slippage_bps, notional,
        order_id, execution_id, signal_id, market, currency, strategy).

        Args:
            orders: List of order dicts from Step 6.

        Returns:
            Number of trades written.
        """
        if not orders:
            return 0

        db_path = self._get_db_path()
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")

        written: int = 0
        today: str = date.today().isoformat()
        now: str = datetime.now().isoformat()

        try:
            for order in orders:
                # Skip rejected orders
                if order.get("rejected"):
                    continue

                ticker: str = order.get("ticker", "")
                if not ticker:
                    continue

                side: str = str(order.get("side", "")).upper()
                quantity: int = int(float(order.get("quantity", 0)))
                price: float = float(order.get("price", 0.0))
                if quantity <= 0 or price <= 0:
                    continue

                notional: float = float(order.get("value", price * quantity))
                commission: float = float(order.get("commission", 0.0))
                slippage_bps: float = float(order.get("slippage_bps", 0.0))
                order_id: str = str(order.get("order_id", ""))
                execution_id: str = str(order.get("execution_id", order_id))
                signal_id: str = str(order.get("signal_id", ""))
                strategy: str = str(order.get("strategy", "pipeline"))
                market: str = (
                    "HK" if ".HK" in ticker
                    else "SG" if ".SI" in ticker
                    else "AU" if ".AX" in ticker
                    else "NZ" if ".NZ" in ticker
                    else "US"
                )
                currency: str = (
                    "HKD" if ".HK" in ticker
                    else "SGD" if ".SI" in ticker
                    else "AUD" if ".AX" in ticker
                    else "NZD" if ".NZ" in ticker
                    else "USD"
                )

                conn.execute(
                    """INSERT INTO trades
                       (id, ticker, trade_date, trade_time, side, quantity, price,
                        commission, slippage_bps, notional, order_id, execution_id,
                        signal_id, market, currency, strategy, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(_uuid.uuid4()),
                        ticker,
                        today,
                        now,
                        side,
                        quantity,
                        round(price, 4),
                        round(commission, 4),
                        round(slippage_bps, 2),
                        round(notional, 2),
                        order_id,
                        execution_id,
                        signal_id,
                        market,
                        currency,
                        strategy,
                        now,
                        now,
                    ),
                )
                written += 1

            conn.commit()
            logger.debug(f"  📈 trades → DB: {written} 笔写入 trades 表")
        except Exception as e:
            logger.warning(f"trades DB write failed (non-critical): {e}")
        finally:
            conn.close()

        return written

    # ═══════════════════════════════════════════════════════════════
    # Helpers
    # ═══════════════════════════════════════════════════════════════

    async def _get_live_prices(self) -> Dict[str, float]:
        """Fetch real-time prices for all portfolio positions.

        Tries the data-service HTTP endpoint first, falls back to
        portfolio's internal ``_last_prices`` cache.

        Returns:
            ticker → price (USD) mapping.  Empty dict on total failure.
        """
        prices: Dict[str, float] = {}
        tickers: List[str] = list(self.portfolio.positions.keys())
        if not tickers:
            return prices

        try:
            http = await self._get_http()
            for ticker in tickers[:20]:  # Cap parallel fetches
                try:
                    resp = await http.get(
                        f"{self.service_urls['data']}/api/v2/data/realtime/{ticker}"
                    )
                    if resp.status_code == 200:
                        rt = resp.json()
                        rt_data = rt.get("data", rt)
                        px = float(rt_data.get("price", rt_data.get("close", 0.0)))
                        if px > 0:
                            prices[ticker] = px
                except Exception:
                    pass
        except Exception as exc:
            logger.debug(f"_get_live_prices HTTP failed: {exc}")

        # Fallback: use cached last prices if HTTP failed for some tickers
        for ticker in tickers:
            if ticker not in prices:
                cached = self.portfolio._last_prices.get(ticker, 0.0)
                if cached > 0:
                    prices[ticker] = cached

        return prices

    async def _push_step_update(self, step: int, data: Dict) -> None:
        """Push a per-step update to the WebSocket dashboard.

        Guards on ENABLE_WS_PUSH config — no-op when disabled.

        Args:
            step: Step number (0-7, or -1 for circuit breaker).
            data: Step-specific payload.
        """
        if not self.config.ENABLE_WS_PUSH:
            return
        await self.ws_pusher.push_step_update(self.cycle_count, step, data)

    # ═══════════════════════════════════════════════════════════════
    # P1-4: v2 HTTP Retry Helper
    # ═══════════════════════════════════════════════════════════════

    async def _retry_http_call(
        self,
        method: str,
        url: str,
        max_retries: int = 3,
        **kwargs,
    ) -> Optional[Dict]:
        """指数退避重试 HTTP 调用。

        v2 服务不可用时自动重试，全部失败返回 None 由调用方走
        v1 fallback。

        Args:
            method: HTTP method (``"GET"`` / ``"POST"``).
            url: Full URL.
            max_retries: Max attempts (default 3).
            **kwargs: Passed to ``httpx.AsyncClient.request``.

        Returns:
            Parsed JSON dict, or None if all retries exhausted.
        """
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.request(method, url, **kwargs)
                    resp.raise_for_status()
                    return resp.json()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500:
                    # 4xx: client error — don't retry.
                    logger.debug(
                        f"HTTP {exc.response.status_code} for {url} — not retrying"
                    )
                    return None
                # 5xx: server error — retry.
                wait: int = 2 ** attempt
                logger.warning(
                    f"HTTP {exc.response.status_code} retry {attempt + 1}/{max_retries} "
                    f"for {url}, waiting {wait}s"
                )
            except (httpx.TimeoutException, httpx.ConnectError, OSError) as exc:
                wait: int = 2 ** attempt
                logger.warning(
                    f"HTTP retry {attempt + 1}/{max_retries} for {url}: {exc}, waiting {wait}s"
                )
            except Exception as exc:
                logger.debug(f"HTTP unrecoverable for {url}: {exc}")
                return None

            if attempt < max_retries - 1:
                await asyncio.sleep(wait)

        logger.warning(f"HTTP exhausted {max_retries} retries for {url}")
        return None

    # ═══════════════════════════════════════════════════════════════
    # P2-3: Force Sell
    # ═══════════════════════════════════════════════════════════════

    def _execute_force_sells(self) -> None:
        """启动时强制清仓 FORCE_SELL_TICKERS 中的持仓。

        遍历 config.FORCE_SELL_TICKERS 列表，对每只在手持仓
        签发市价卖出单。paper 模式仅更新本地状态；live 模式
        同时通过 Tiger 下单。
        """
        positions: Dict[str, float] = dict(self.portfolio.positions)
        for ticker in self.config.FORCE_SELL_TICKERS:
            if ticker in positions and positions[ticker] != 0.0:
                shares: float = abs(positions[ticker])
                logger.warning(f"🔴 强制清仓: {ticker} × {shares} 股")

                try:
                    if self.tiger_ready:
                        self.tiger.place_order(
                            ticker=ticker,
                            action="SELL",
                            quantity=int(shares),
                            order_type="MKT",
                        )
                except Exception as exc:
                    logger.warning(f"强制清仓 Tiger 下单异常 {ticker}: {exc}")

                # 更新本地状态。
                self.portfolio.execute_trade(
                    ticker=ticker,
                    side="sell",
                    price=0.0,  # Market order — exact fill unknown.
                    quantity=shares,
                    strategy="force_sell",
                )
                logger.info(f"  ✅ 强制清仓完成: {ticker} × {shares}")

    # ═══════════════════════════════════════════════════════════════
    # P2-1: Git Auto-Sync
    # ═══════════════════════════════════════════════════════════════

    def _git_sync(self) -> None:
        """触发一次 git add/commit/pull/push。

        通过 ``shared.git_sync.git_sync`` 执行，全部异常静默
        降级不阻塞交易循环。
        """
        logger.info("🔄 Git auto-sync...")
        ok: bool = git_sync(str(Path(__file__).resolve().parent))
        if ok:
            logger.debug("Git sync succeeded")
        else:
            logger.debug("Git sync skipped or failed (see debug log)")


# ═══════════════════════════════════════════════════════════════
# 命令行入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Quant AI Trader v2 — Trading Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="循环间隔（秒），默认 300 (5分钟)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="运行一次交易循环后退出（开发/测试用）",
    )
    args = parser.parse_args()

    pipeline = TradingPipeline(config=pipeline_config)

    async def _main() -> None:
        try:
            if args.once:
                logger.info("🚀 单次运行模式（--once）")
                result = await pipeline.run_cycle()
                if result:
                    logger.info(f"✅ 单次完成: {result}")
                else:
                    logger.warning("⚠️ 单次运行无结果（可能数据不足）")
            else:
                await pipeline.run(interval_seconds=args.interval)
        finally:
            await pipeline.close()

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        logger.info("⏹ Trading Pipeline 收到退出信号")
        sys.exit(0)
