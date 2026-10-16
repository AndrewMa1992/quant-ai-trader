"""
Trading Pipeline — v2 core trading orchestrator
===============================================
Replaces v1 auto_trader.py, chaining six microservices through a T+0 trading cycle.

v2.2 refactor (T04):
  • Pre-cycle: trading-day rollover / market session / Tiger sync / circuit breaker / leverage / daily trade cap
  • Seven-step main path: Universe → Data → Factors → Inference → Risk → Optimize → Execute
  • Post-cycle: short-position repair / WS push / state persist
  • TigerExecutor unifies live/paper execution

Seven-step flow:
  0. Get Active Universe — fetch the day's active stock universe
  1. Fetch Market Data — HTTP → data-service:8011
  2. Compute Factors — local FactorEngine
  3. Run Inference — local InferenceEngine
  4. Apply Risk Checks — RiskGate (four-layer risk)
  5. Optimize Portfolio — HTTP → execution-service:8016 BL optimizer
  6. Execute Rebalance — TigerExecutor (live/paper)
  7. Record Performance — write to shared database
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

# ── v2 service modules (existing, do not modify) ────────────
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

# ── v2 shared modules ─────────────────────────────────────────
from shared.portfolio_manager import PortfolioManager
from shared.risk_manager import RiskManager
from shared.tiger_executor import TigerExecutor
from shared.daily_state import DailyState
from shared.ws_pusher import WsPusher
from shared.market_session import get_market_status, is_any_market_open
from shared.git_sync import git_sync


class TradingPipeline:
    """v2 core trading orchestrator.

    Chains seven steps through the v2 microservice pipeline, replacing v1 auto_trader.py.
    Each step has its own try/except; a single-step failure does not abort the cycle.

    Pre-cycle checks (P0/P1):
      - Trading-day rollover → reset risk controls and day-start data
      - Market session → mark-to-market only when markets are closed
      - Tiger sync → overwrite-fetch positions/cash
      - Portfolio circuit breaker → liquidate if daily loss ≥5% or drawdown ≥25%
      - Leverage hard rule → block all buys when leverage ≥ 1.001
      - Daily trade cap → skip trading and mark-to-market only once the cap is hit

    Post-cycle checks:
      - Short-position repair → detect negative holdings and buy back
      - WS push → push each step and the cycle summary to the frontend
      - State persist → persist portfolio/risk state
    """

    def __init__(self, config: PipelineConfig) -> None:
        self.config: PipelineConfig = config
        self.service_urls: Dict[str, str] = config.SERVICE_BASE_URLS
        self.logger = logger  # alias for readability

        # ── Local engines (v2 existing; degrade to stub on import failure) ──
        logger.info("Initializing local engines...")
        if FactorEngine is not None:
            self.factor_engine: FactorEngine = FactorEngine()
            self.factor_engine.register_all()
            logger.info(f"  ✅ FactorEngine ready ({len(self.factor_engine.factors)} factors)")
        else:
            self.factor_engine = None  # type: ignore[assignment]
            logger.warning("  ⚠️ FactorEngine unavailable — stub mode")

        if InferenceEngine is not None:
            self.inference_engine: InferenceEngine = InferenceEngine()
            load_status = self.inference_engine.load_models()
            loaded_count = sum(1 for v in load_status.values() if v)
            from services.model_infer_service.checkpoints import checkpoint_mtime
            self._checkpoint_mtime = checkpoint_mtime()
            logger.info(f"  ✅ InferenceEngine ready ({loaded_count}/{len(load_status)} models loaded)")
        else:
            self.inference_engine = None  # type: ignore[assignment]
            logger.warning("  ⚠️ InferenceEngine unavailable — stub mode")

        # ── Risk components ──────────────────────────────────
        logger.info("Initializing risk components...")
        if CircuitBreaker is not None:
            self.circuit_breaker: CircuitBreaker = CircuitBreaker()
            logger.info("  ✅ CircuitBreaker ready")
        else:
            self.circuit_breaker = None  # type: ignore[assignment]
            logger.warning("  ⚠️ CircuitBreaker unavailable — stub mode")
        self.risk_gate: RiskGate = RiskGate(
            circuit_breaker=self.circuit_breaker,
            risk_service_url=self.service_urls["risk"],
            constraints={
                "barra_exposure_max_z": config.BARRA_EXPOSURE_MAX_Z,
                "var_limit_pct": config.VAR_LIMIT_PCT,
                "cvar_limit_pct": config.CVAR_LIMIT_PCT,
            },
        )
        logger.info("  ✅ RiskGate (four-layer risk) ready")

        # ── Portfolio management ─────────────────────────────
        logger.info("Initializing portfolio manager...")
        try:
            from configs.settings import settings as _settings

            _init_cap = float(_settings.TRADING_INITIAL_CAPITAL)
        except Exception:
            _init_cap = 1700.0
        self.portfolio: PortfolioManager = PortfolioManager(
            initial_capital=_init_cap,
        )
        # Try to load existing state
        self.portfolio.load_state("data/portfolio_state.json")
        # Recover if a prior Tiger zero-NAV sync wiped local buying power
        if self.portfolio.ensure_buying_power(_init_cap):
            logger.warning(
                f"  💰 Paper capital restored to ${_init_cap:,.2f} "
                f"(Tiger paper account was empty / unfunded)"
            )
        logger.info(
            f"  ✅ PortfolioManager ready "
            f"(initial ${_init_cap:,.2f}, "
            f"cash ${self.portfolio.cash:,.2f}, "
            f"{len(self.portfolio.positions)} positions)"
        )

        # ── Risk manager (v2) ────────────────────────────────
        logger.info("Initializing risk manager (v2)...")
        self.risk_manager: RiskManager = RiskManager(
            initial_capital=self.portfolio.initial_capital,
            breaker_mode="hard",
            max_daily_trades=config.MAX_DAILY_TRADES,
        )
        self.risk_manager.load_state("data/risk_state.json")
        self.risk_manager.sync_portfolio_value(
            self.portfolio.total_value,
            self.portfolio.cash,
        )
        logger.info("  ✅ RiskManager (v2) ready")

        # ── Daily state tracking ──────────────────────────────
        self.daily_state: DailyState = DailyState(
            daily_start_value=self.portfolio.total_value,
        )
        logger.info("  ✅ DailyState ready")

        # ── Tiger connection ─────────────────────────────────
        logger.info("Initializing Tiger connection...")
        self.tiger = _tiger_bridge
        self.tiger_ready: bool = self.tiger.connect()
        if self.tiger_ready:
            logger.info("  ✅ Tiger Broker connected")
        else:
            logger.warning("  ⚠️ Tiger Broker not connected — Paper Trading mode")

        # ── Executor (sim accounts default to paper; live only when explicit live and not sim) ──
        logger.info("Initializing TigerExecutor...")
        from shared.execution_mode import get_execution_mode, is_simulation_mode

        exec_mode = get_execution_mode()
        if is_simulation_mode():
            logger.info("  🔒 Simulation account locked — EXECUTION_MODE=paper")
        self.executor: TigerExecutor = TigerExecutor(
            mode=exec_mode if (self.tiger_ready and exec_mode == "live") else "paper",
            portfolio=self.portfolio,
            risk=self.risk_manager,
            tiger_bridge=self.tiger,
        )
        logger.info(f"  ✅ TigerExecutor ready (mode={self.executor.mode})")

        # ── WebSocket pusher ─────────────────────────────────
        api_base: str = self.service_urls.get("api", "")
        self.ws_pusher: WsPusher = WsPusher(
            api_url=api_base,
            enabled=config.ENABLE_WS_PUSH,
        )
        if config.ENABLE_WS_PUSH:
            logger.info("  ✅ WsPusher enabled")
        else:
            logger.info("  ⚠️ WsPusher disabled (ENABLE_WS_PUSH=False)")

        # ── Data directory ───────────────────────────────────
        self.data_dir: Path = Path("data/daily")
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # ── SQLite / Redis warm-up ──────────────────────────
        try:
            from shared.database.engine import optimize_sqlite_file

            optimize_sqlite_file("data/quant_trader.db")
        except Exception as e:
            logger.debug(f"SQLite optimize skipped: {e}")
        try:
            from shared.market_cache import sync_cache_portfolio

            sync_cache_portfolio({
                "cash": self.portfolio.cash,
                "total_value": self.portfolio.total_value,
                "positions": len(self.portfolio.positions),
            })
            logger.info("  ✅ Redis market cache warmed (or in-memory degrade)")
        except Exception as e:
            logger.info(f"  ⚠️ Redis cache warm skipped: {e}")

        # ── HTTP client ──────────────────────────────────────
        self._http: Optional[httpx.AsyncClient] = None

        # ── State ────────────────────────────────────────────
        self.cycle_count: int = 0
        self.trades_today: int = 0
        self.trade_date: str = datetime.now().strftime("%Y-%m-%d")
        self._market_round_index: int = 0

        logger.info("=" * 60)
        logger.info("TradingPipeline initialization complete")
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
        """Main loop: run one trading cycle every interval_seconds.

        Args:
            interval_seconds: Cycle interval; default 300s (5 min)
        """
        logger.info(f"🚀 Trading pipeline started — interval {interval_seconds}s")

        # ── P2-3: Force-sell specified holdings ──────────────
        if self.config.FORCE_SELL_TICKERS:
            try:
                self._execute_force_sells()
            except Exception as exc:
                logger.error(f"Force-sell error (non-fatal): {exc}")

        try:
            while True:
                try:
                    await self.run_cycle()
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    logger.exception(f"❌ Cycle #{self.cycle_count} error: {e}")
                    retry_wait: int = 60
                    logger.info(f"Sleeping {retry_wait}s then retrying...")
                    await asyncio.sleep(retry_wait)
                    continue

                # ── P2-1: Git auto-sync (every 6 cycles) ─────────
                if (
                    self.config.GIT_AUTO_SYNC
                    and self.cycle_count > 0
                    and self.cycle_count % 6 == 0
                ):
                    try:
                        self._git_sync()
                    except Exception as exc:
                        logger.debug(f"Git sync error (silent): {exc}")

                logger.info(f"Sleeping {interval_seconds // 60} minutes...")
                await asyncio.sleep(interval_seconds)
        finally:
            await self.close()

    async def run_cycle(self) -> Optional[Dict]:
        """Run one complete T+0 trading cycle.

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
        # Pre-cycle checks
        # ═══════════════════════════════════════════════════════════

        # ── 1. Trading-day rollover detection ────────────────
        if self.daily_state.check_date_roll():
            self.risk_manager.reset_daily_state()
            self.daily_state.reset_for_new_day(self.portfolio.total_value)
            self.trades_today = 0
            self.trade_date = self.daily_state.trade_date

        # ── 2. P0-3: Market-session check ─────────────────────
        if self.config.TRADING_HOURS_ONLY:
            try:
                if not is_any_market_open():
                    logger.info("📴 All markets closed, skipping trades — mark-to-market only")
                    prices = await self._get_live_prices()
                    self.portfolio.update_value(prices)
                    await self._push_step_update(0, {
                        "status": "markets_closed",
                        "portfolio": self.portfolio.get_metrics(),
                    })
                    return None
            except Exception as e:
                logger.warning(f"Market-session check error: {e}, continuing")

        # ── 3. P0-4, P0-5: Tiger state sync ──────────────────
        if self.tiger_ready:
            try:
                sync_result = self.portfolio.sync_from_tiger(self.tiger, force=False)
                src = sync_result.get("source", "")
                if sync_result.get("synced"):
                    self.risk_manager.sync_portfolio_value(
                        self.portfolio.total_value,
                        self.portfolio.cash,
                        is_tiger_sync=True,
                    )
                    self.risk_manager.update_portfolio_state(
                        self.portfolio.total_value,
                        self.portfolio.cash,
                        dict(self.portfolio.positions),
                        {},
                    )
                    if self.circuit_breaker is not None:
                        self.circuit_breaker.set_nav(self.portfolio.total_value)
                    logger.info(
                        f"🔄 Tiger sync: {sync_result.get('positions')} positions, "
                        f"cash ${sync_result.get('cash', 0):,.2f}"
                    )
                elif src == "tiger_zero_nav_preserved":
                    # Keep risk/local book aligned with preserved capital
                    self.risk_manager.sync_portfolio_value(
                        self.portfolio.total_value,
                        self.portfolio.cash,
                        is_tiger_sync=False,
                    )
                    logger.warning(
                        "🛡️ Tiger paper account NAV≈0 — local capital preserved, continuing local paper orders"
                    )
            except Exception as e:
                logger.warning(f"Tiger sync error (continuing with local data): {e}")

        # ── 4. P0-2: Portfolio circuit-breaker check ──────────
        try:
            prices = await self._get_live_prices()
            self.portfolio.update_value(prices)
        except Exception:
            prices = {}

        # Keep RiskManager positions in sync so liquidation is not a no-op
        self.risk_manager.update_portfolio_state(
            self.portfolio.total_value,
            self.portfolio.cash,
            dict(self.portfolio.positions),
            prices,
        )
        if self.circuit_breaker is not None:
            try:
                self.circuit_breaker.set_nav(self.portfolio.total_value)
            except Exception:
                pass

        report = self.risk_manager.check_circuit_breaker()
        if report.circuit_breaker and self.risk_manager.breaker_mode == "hard":
            logger.error(f"🚨 Circuit breaker tripped: {report.reason}")
            try:
                from shared.kill_switch import get_kill_switch

                get_kill_switch().engage(report.reason or "circuit_breaker", engaged_by="trading_pipeline")
            except Exception:
                pass
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
            # Re-sync positions with latest prices before liquidation
            self.risk_manager.update_portfolio_state(
                self.portfolio.total_value,
                self.portfolio.cash,
                dict(self.portfolio.positions),
                prices,
            )
            liq_records = self.risk_manager.liquidate_all(prices, self.tiger)
            self.portfolio.apply_liquidation(liq_records, prices)
            await self._push_step_update(-1, {
                "circuit_breaker": True,
                "reason": report.reason,
                "liquidated": len(liq_records),
            })
            return None

        # ── 5. P1-1: Leverage check ───────────────────────────
        leverage_blocked: bool = False
        if self.tiger_ready:
            try:
                acct = self.tiger.get_account_info()
                if acct and self.risk_manager.check_leverage(acct):
                    logger.warning("🚫 Leverage hard rule: blocking all buys")
                    await self.ws_pusher.push_alert(
                        "leverage",
                        f"Tiger leverage {acct.get('leverage', '?')} ≥ 1.001 — blocking all buys",
                    )
                    leverage_blocked = True
            except Exception as e:
                logger.warning(f"Leverage check error: {e}")

        # Already levered: keep the cycle so sells of existing longs can
        # raise cash. New buys are refused downstream.
        self._block_buys = bool(leverage_blocked)
        if self._block_buys:
            logger.error(
                "🚫 Account is on margin — new buys blocked; "
                "sells of existing long positions still run"
            )

        # ── 6. P1-2: Daily trade cap ──────────────────────────
        if self.risk_manager.check_daily_limit():
            logger.info(
                f"📊 Daily trade cap reached ({self.risk_manager.trades_today}/"
                f"{self.risk_manager.max_daily_trades}), mark-to-market only"
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
            logger.warning("Active universe is empty, skipping this cycle")
            return None
        logger.info(f"Step 0: universe {len(tickers)} names")
        await self._push_step_update(0, {"tickers": len(tickers)})

        # Step 1: Fetch Market Data
        data: Dict = await self._fetch_market_data(tickers)
        if not data or len(data) < 2:
            logger.warning("Insufficient market data, skipping this cycle")
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
        self._attach_latest_prices(signals, data)
        if not signals:
            logger.warning("No valid signals, skipping this cycle")
            return None
        await self._push_step_update(3, {"raw_signals": len(signals)})

        # ── DB Write: persist signals to the signals table ────────
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

        # ── DB Write: persist trades to the trades table ──────────
        self._write_trades_to_db(orders)
        await self._push_step_update(6, {
            "orders": len(orders),
            "trades_today": self.trades_today,
        })

        # Step 7: Record Performance
        await self._record_performance(orders)

        # ═══════════════════════════════════════════════════════════
        # Post-cycle checks
        # ═══════════════════════════════════════════════════════════

        # ── 7. P1-3: Short-position repair ────────────────────
        try:
            if not prices:
                prices = await self._get_live_prices()
            fixed: int = self.risk_manager.fix_short_positions(
                self.portfolio, self.tiger, prices,
            )
            if fixed:
                logger.info(f"🔧 Short-position repair: {fixed} names")
        except Exception as e:
            logger.warning(f"Short-position repair error: {e}")

        # ── 8. Persist state ──────────────────────────────────
        try:
            self.portfolio.save_state()
            self.risk_manager.save_state("data/risk_state.json")
        except Exception as e:
            logger.warning(f"State persist error: {e}")

        # ── P2-2: Full Tiger sync to local DB (every cycle + Redis/WS) ──
        tiger_snap: Dict = {}
        if self.tiger_ready:
            try:
                tiger_snap = self.tiger.sync_all_to_db() or {}
                # Also refresh in-memory portfolio from Tiger paper
                try:
                    self.portfolio.sync_from_tiger(self.tiger, force=False)
                except Exception:
                    pass
                logger.info(
                    f"Tiger sync: positions={tiger_snap.get('positions_synced', 0)} "
                    f"NAV={tiger_snap.get('nav', 0)}"
                )
            except Exception as e:
                logger.warning(f"Tiger sync_all_to_db: {e}")

        # ── Redis: cycle + portfolio + signals ───────────────
        try:
            from shared.market_cache import (
                sync_cache_cycle,
                sync_cache_portfolio,
                sync_cache_signals,
            )

            sync_cache_signals(signals if isinstance(signals, list) else [])
            sync_cache_portfolio({
                "cash": self.portfolio.cash,
                "total_value": self.portfolio.total_value,
                "n_positions": len(self.portfolio.positions),
                "cycle": self.cycle_count,
            })
            sync_cache_cycle({
                "cycle": self.cycle_count,
                "orders": len(orders),
                "signals": len(signals) if isinstance(signals, list) else 0,
                "nav": self.portfolio.total_value,
                "mode": getattr(self.executor, "mode", "paper"),
            })
        except Exception as e:
            logger.debug(f"Redis cycle publish skipped: {e}")

        # Push Tiger snapshot to frontend WS room
        try:
            if tiger_snap and not tiger_snap.get("error"):
                await self.ws_pusher.push_tiger_snapshot(tiger_snap)
            else:
                # Local paper book snapshot when Tiger offline
                await self.ws_pusher.push_tiger_snapshot({
                    "type": "tiger_snapshot",
                    "source": "local_paper",
                    "nav": self.portfolio.total_value,
                    "cash": self.portfolio.cash,
                    "positions": [
                        {
                            "ticker": t,
                            "quantity": s,
                            "shares": s,
                            "avg_cost": self.portfolio.avg_costs.get(t, 0),
                            "market_value": s * self.portfolio._last_prices.get(
                                t, self.portfolio.avg_costs.get(t, 0)
                            ),
                        }
                        for t, s in self.portfolio.positions.items()
                        if s != 0
                    ],
                })
        except Exception as e:
            logger.debug(f"tiger snapshot push skipped: {e}")

        # ── Cycle summary ────────────────────────────────────
        elapsed: float = time.time() - t_start
        logger.info(
            f"⏱  Cycle #{self.cycle_count} complete "
            f"| elapsed {elapsed:.1f}s "
            f"| signals {len(signals)} → passed {len(approved)} → orders {len(orders)}"
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

        # ── P1-5: WS push cycle summary ───────────────────────
        await self.ws_pusher.push_summary(self.cycle_count, cycle_summary)

        return cycle_summary

    # ═══════════════════════════════════════════════════════════════
    # Step 0: Get Active Universe
    # ═══════════════════════════════════════════════════════════════

    async def _get_active_universe(self) -> List[str]:
        """Fetch the day's active stock universe.

        Returns:
            List of ticker strings, capped at MAX_TICKERS_PER_CYCLE.
        """
        t0: float = time.time()
        tickers: List[str] = []
        try:
            # v2: fetch universe from data-service (with retry)
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
            logger.warning(f"Failed to fetch universe: {e}, using v1 fallback")
            tickers = self._get_active_universe_v1_fallback()

        # Filter and cap count
        tickers = [t for t in tickers if isinstance(t, str) and t]

        # ── Market rotation: prefer currently open markets, then round-robin ──
        if self.config.MARKET_ROUND_ROBIN and self.config.MARKET_ROTATION:
            from shared.market_session import is_market_open, next_open_markets

            rotation = list(self.config.MARKET_ROTATION)
            prefer_open = bool(getattr(self.config, "PREFER_OPEN_MARKETS", True))
            open_now = next_open_markets(rotation) if prefer_open else []
            if open_now:
                # Pick next open market in rotation order
                start = self._market_round_index % len(rotation)
                target_market = None
                for i in range(len(rotation)):
                    cand = rotation[(start + i) % len(rotation)]
                    if cand in open_now:
                        target_market = cand
                        self._market_round_index = (start + i + 1) % len(rotation)
                        break
                if target_market is None:
                    target_market = open_now[0]
                    self._market_round_index += 1
            else:
                target_market = rotation[self._market_round_index % len(rotation)]
                self._market_round_index += 1
                # When nothing open (rare with US 24h), still cycle for data refresh
                logger.info(f"  📴 No open market hit, still analyzing {target_market}")

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
            open_flag = is_market_open(target_market)
            logger.info(
                f"  🎯 Market rotation: {target_market} open={open_flag}, {len(tickers)} names"
            )

        tickers = tickers[: self.config.MAX_TICKERS_PER_CYCLE]

        elapsed: float = time.time() - t0
        logger.info(f"  Step 0 complete ({elapsed:.1f}s): {len(tickers)} names")
        return tickers

    def _get_active_universe_v1_fallback(self) -> List[str]:
        """v1 fallback: fetch from backend stock universe."""
        try:
            from backend.data_engine.stock_universe import stock_universe
            return stock_universe.all_tickers
        except Exception:
            pass
        # Hardcoded minimal fallback
        return ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]

    def _models_are_stale(self, max_age_days: int = 14) -> bool:
        """True if any core checkpoint is older than max_age_days."""
        from pathlib import Path
        import time as _time

        root = Path("data/models")
        names = ("gbdt_v2.joblib", "transformer_v2.pt", "tcn_v2.pt", "tft_v2.pt")
        now = _time.time()
        found = 0
        stale = 0
        for name in names:
            p = root / name
            if not p.exists():
                continue
            found += 1
            age_days = (now - p.stat().st_mtime) / 86400.0
            if age_days > max_age_days:
                stale += 1
        if found == 0:
            return True
        return stale >= max(1, found // 2)

    # ═══════════════════════════════════════════════════════════════
    # Step 1: Fetch Market Data
    # ═══════════════════════════════════════════════════════════════

    async def _fetch_market_data(self, tickers: List[str]) -> Dict:
        """Fetch market data (v1 fallback + ParquetStore sync).

        Use v1 MarketDataEngine to fetch data and also write ParquetStore
        for v2 InferenceEngine to read.
        """
        result = self._fetch_market_data_v1_fallback(tickers)

        # Sync-write ParquetStore for the v2 inference engine
        if result:
            try:
                from services.data_service.storage.parquet_store import ParquetStore
                store = ParquetStore()
                for ticker, d in result.items():
                    if isinstance(d, dict) and "ohlcv" in d:
                        continue
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
        """v1 fallback: use backend MarketDataEngine."""
        try:
            from backend.data_engine import MarketDataEngine
            from backend.data_engine.data_pipeline import DataPipeline

            engine = MarketDataEngine()
            pipeline = DataPipeline()
            data_dict: Dict = {}
            try:
                engine.warm_history(tickers, period="2y", interval="1d")
            except Exception as exc:
                logger.info(f"history warm skipped: {exc}")
            errors: int = 0
            store = None
            try:
                from services.data_service.storage.parquet_store import ParquetStore

                store = ParquetStore()
            except Exception:
                store = None

            for ticker in tickers:
                try:
                    df = engine.get_historical_data(ticker, period="2y", interval="1d")
                    if df is not None and not df.empty:
                        if store is not None:
                            try:
                                store.write_daily(ticker, df)
                            except Exception as exc:
                                logger.debug(f"daily parquet skip {ticker}: {exc}")
                        try:
                            from shared.nn_samples import record_daily_window

                            record_daily_window(ticker, df)
                        except Exception as exc:
                            logger.debug(f"nn sample skip {ticker}: {exc}")
                        processed = pipeline.process(df)
                        if processed is not None:
                            fcols = [
                                c for c in pipeline.FEATURE_COLUMNS
                                if c in processed.columns
                            ]
                            if len(fcols) >= 30:
                                close_px = 0.0
                                for col in ("close", "Close"):
                                    if col in df.columns:
                                        close_px = float(df[col].iloc[-1])
                                        break
                                if close_px <= 0 and "close" in processed.columns:
                                    close_px = float(processed["close"].iloc[-1])
                                payload = {
                                    "features": processed[fcols].values,
                                    "close": close_px,
                                }
                                ohlcv_cols = [
                                    col for col in ("open", "high", "low", "close", "volume")
                                    if col in df.columns
                                ]
                                if ohlcv_cols:
                                    payload["ohlcv"] = df[ohlcv_cols].copy()
                                data_dict[ticker] = payload
                    else:
                        errors += 1
                except Exception:
                    errors += 1

            logger.info(f"  Step 1 fallback: {len(data_dict)}/{len(tickers)} succeeded, {errors} failed")
            return data_dict
        except Exception as e:
            logger.error(f"Step 1 fallback also failed: {e}")
            return {}

    # ═══════════════════════════════════════════════════════════════
    # Step 2: Compute Factors
    # ═══════════════════════════════════════════════════════════════

    async def _compute_factors(self, data: Dict):
        """Local FactorEngine factor computation.

        Args:
            data: {ticker: {features: ndarray, close: float}, ...}

        Returns:
            DataFrame with factor values indexed by ticker.
        """
        t0: float = time.time()
        if self.factor_engine is None or not data:
            logger.warning("  Step 2: FactorEngine stub — scoring from daily returns")
            rows = []
            for ticker, payload in (data or {}).items():
                row = {"ticker": str(ticker)}
                ohlcv = payload.get("ohlcv") if isinstance(payload, dict) else None
                self._stamp_return_score(row, ohlcv)
                rows.append(row)
            return pd.DataFrame(rows)

        try:
            # Convert v1 fallback format → DataFrame dict for FactorEngine
            dfs: dict = {}
            ohlcv_by_ticker: dict = {}
            for ticker, d in data.items():
                if isinstance(d, dict) and isinstance(d.get("ohlcv"), pd.DataFrame):
                    ohlcv_by_ticker[ticker] = d["ohlcv"]
                    dfs[ticker] = d["ohlcv"]
                    continue
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
                    self._stamp_return_score(row, ohlcv_by_ticker.get(ticker))
                    rows.append(row)
                else:
                    row = {"ticker": str(ticker)}
                    self._stamp_return_score(row, ohlcv_by_ticker.get(ticker))
                    rows.append(row)

            factor_df = pd.DataFrame(rows)
            elapsed: float = time.time() - t0
            n_tickers: int = len(factor_df)
            n_factors: int = factor_df.shape[1] - 1 if factor_df.shape[1] > 1 else 0
            logger.info(f"  Step 2 ({elapsed:.1f}s): {n_tickers} tickers × {n_factors} factors")
            return factor_df
        except Exception as e:
            logger.error(f"Step 2 factor computation failed: {e}", exc_info=True)
            return pd.DataFrame({"ticker": list(data.keys())})

    # ═══════════════════════════════════════════════════════════════
    # Step 3: Run Inference
    # ═══════════════════════════════════════════════════════════════

    async def _run_inference(self, factor_df, tickers: List[str]) -> List[Dict]:
        """Local InferenceEngine model inference — Top-N signal selection.

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

        # GPU train pushes data/models to main. Reload when those files change.
        try:
            from services.model_infer_service.checkpoints import checkpoint_mtime
            max_age = int(getattr(self.config, "MODEL_MAX_AGE_DAYS", 14))
            stamp = checkpoint_mtime()
            if stamp > float(getattr(self, "_checkpoint_mtime", 0.0)) + 1.0:
                self.inference_engine.load_models()
                self._checkpoint_mtime = stamp
                logger.info("  Step 3: reloaded checkpoints from data/models")
            stale = self._models_are_stale(max_age_days=max_age)
            if stale:
                logger.warning(
                    f"  Step 3: models older than {max_age}d — size/threshold de-risk"
                )
        except Exception as e:
            logger.debug(f"model freshness check skipped: {e}")
            stale = False

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
                logger.warning("  Step 3: no tickers with data, skipping inference")
                return []

            # Regime adapt once per cycle (SPY / fallback)
            try:
                adapt = self.inference_engine.adapt_from_market()
                logger.info(
                    f"  Step 3: market regime={adapt.get('regime')} "
                    f"(fitted={adapt.get('fitted')}, bench={adapt.get('benchmark')})"
                )
            except Exception as adapt_exc:
                logger.debug(f"  Step 3: regime adapt skipped: {adapt_exc}")

            # Ensure factor_df has a 'ticker' column for batch inference
            if "ticker" not in factor_df.columns and len(factor_df) <= len(tickers):
                factor_df = factor_df.copy()
                factor_df["ticker"] = tickers[:len(factor_df)]

            signals: List[Dict] = self.inference_engine.generate_signals_batch(
                factor_df,
                top_n=self.config.TOP_N_SIGNALS,
                min_threshold=(
                    self.config.SIGNAL_THRESHOLD_MIN * (1.5 if stale else 1.0)
                ),
                min_confidence=self.config.MIN_CONFIDENCE + (0.1 if stale else 0.0),
            )

            if stale and signals:
                # Halve conviction when models are stale
                for s in signals:
                    if "signal" in s:
                        s["signal"] = float(s["signal"]) * 0.5
                    if "strength" in s:
                        s["strength"] = float(s["strength"]) * 0.5
                    if "confidence" in s:
                        s["confidence"] = float(s["confidence"]) * 0.8

            # Feed ensemble Bayesian weights with this cycle's components
            try:
                weights = self.inference_engine.update_ensemble_from_signals(signals)
                if weights:
                    logger.debug(f"  Step 3: bayesian weights={weights}")
            except Exception as bw_exc:
                logger.debug(f"  Step 3: bayesian update skipped: {bw_exc}")

            elapsed: float = time.time() - t0
            logger.info(
                f"  Step 3 ({elapsed:.1f}s): {len(signals)} signals "
                f"(top {self.config.TOP_N_SIGNALS} by |score|, "
                f"floor={self.config.SIGNAL_THRESHOLD_MIN}, "
                f"min_conf={self.config.MIN_CONFIDENCE})"
            )
            if not signals:
                signals = self._factor_score_fallback(factor_df, tickers)
            return signals
        except Exception as e:
            logger.error(f"Step 3 inference failed: {e}", exc_info=True)
            return self._factor_score_fallback(factor_df, tickers)

    @staticmethod
    def _order_quantity(
        cash: float,
        nav: float,
        strength: float,
        price: float,
        single_order_limit: float = 0.02,
    ) -> int:
        """Share count that stays inside the circuit breaker's single-order limit.

        The breaker rejects when ``quantity * price / NAV`` is above that limit.
        Sizing off 20% of cash was above it, so every signal was blocked.
        """
        if price <= 0:
            return 0
        strength_frac = min(abs(float(strength or 0.0)), 0.20)
        cash_budget = max(float(cash or 0.0), 0.0) * strength_frac
        if nav and nav > 0 and single_order_limit and single_order_limit > 0:
            cap = float(nav) * float(single_order_limit) * 0.95
            budget = min(cash_budget, cap) if cash_budget > 0 else 0.0
        else:
            budget = cash_budget
        if budget <= 0:
            return 0
        return int(budget / float(price))

    @staticmethod
    def _stamp_return_score(row: dict, ohlcv) -> None:
        """Keep a 21-day return on the factor row when the engine did not."""
        if any(str(key).upper() in {"F001", "F002", "F014"} for key in row):
            return
        if not isinstance(ohlcv, pd.DataFrame) or "close" not in getattr(ohlcv, "columns", []):
            return
        if len(ohlcv) < 22:
            return
        close = pd.to_numeric(ohlcv["close"], errors="coerce")
        ret21 = close.pct_change(21).iloc[-1]
        if pd.notna(ret21):
            row["F001"] = float(ret21)

    @staticmethod
    def _attach_latest_prices(signals, data: Dict) -> None:
        """Copy the fetched close onto signals so the risk gate can size orders."""
        if not signals or not isinstance(data, dict):
            return
        for sig in signals:
            if not isinstance(sig, dict):
                continue
            try:
                px = float(sig.get("price") or sig.get("close") or 0)
            except (TypeError, ValueError):
                px = 0.0
            if px > 0:
                sig["price"] = px
                continue
            row = data.get(sig.get("ticker"))
            if not isinstance(row, dict):
                continue
            try:
                px = float(row.get("close") or 0)
            except (TypeError, ValueError):
                px = 0.0
            if px > 0:
                sig["price"] = px
                sig["close"] = px

    def _factor_score_fallback(self, factor_df, tickers: List[str]) -> List[Dict]:
        """When models return no signals, rank by simple factor score so paper can trade.

        Prefer momentum-like columns. Raw OHLC and volume are not scores.
        """
        if factor_df is None or getattr(factor_df, "empty", True):
            return []
        try:
            df = factor_df.copy()
            if "ticker" not in df.columns:
                return []
            skip = {"ticker", "open", "high", "low", "close", "volume", "adj_close"}
            prefer_keys = (
                "mom", "ret", "momentum", "trend", "alpha",
                "f001", "f002", "f003", "f004", "f014",
            )
            prefer = [
                c
                for c in df.columns
                if str(c).lower() not in skip
                and any(k in str(c).lower() for k in prefer_keys)
            ]
            num_cols = [
                c
                for c in (prefer or list(df.columns))
                if str(c).lower() not in skip and pd.api.types.is_numeric_dtype(df[c])
            ]
            if not num_cols:
                return []
            scores = df[num_cols].astype(float).mean(axis=1)
            df = df.assign(_score=scores)
            df = df.dropna(subset=["_score"])
            df = df.sort_values("_score", ascending=False)
            top_n = int(getattr(self.config, "TOP_N_SIGNALS", 10) or 10)
            out: List[Dict] = []
            for _, row in df.head(max(1, top_n)).iterrows():
                ticker = str(row["ticker"])
                if tickers and ticker not in tickers:
                    continue
                score = float(row["_score"])
                if abs(score) < 1e-12:
                    continue
                strength = min(1.0, abs(score) / (abs(scores).max() + 1e-9))
                out.append(
                    {
                        "ticker": ticker,
                        "signal": float(np.sign(score) * strength),
                        "strength": strength,
                        "confidence": 0.45,
                        "decision": "BUY" if score > 0 else "SELL",
                        "source": "factor_fallback",
                    }
                )
            if out:
                logger.warning(
                    f"  Step 3: model empty — factor fallback produced {len(out)} signals"
                )
            return out
        except Exception as exc:
            logger.debug(f"factor fallback skipped: {exc}")
            return []

    # ═══════════════════════════════════════════════════════════════
    # Step 4: Apply Risk Checks
    # ═══════════════════════════════════════════════════════════════

    async def _apply_risk_checks(self, signals: List[Dict]) -> List[Dict]:
        """RiskGate four-layer risk checks.

        Pass each signal through the risk gates; record the reason and skip failures.

        Args:
            signals: List of signal dicts.

        Returns:
            Filtered list of signals that passed all risk checks.
        """
        t0: float = time.time()
        if not self.config.ENABLE_RISK_CHECKS:
            logger.info("  Step 4: risk checks disabled (ENABLE_RISK_CHECKS=False)")
            return signals

        approved: List[Dict] = []
        rejected: List[str] = []
        portfolio_state: Dict = {
            "total_value": self.portfolio.total_value,
            "cash": self.portfolio.cash,
            "positions": dict(self.portfolio.positions),
            "position_values": dict(getattr(self.risk_manager, "position_values", {}) or {}),
        }

        for sig in signals:
            ticker: str = sig.get("ticker", "")
            signal_strength: float = sig.get("signal", sig.get("strength", 0.0))
            confidence: float = sig.get("confidence", 0.5)
            price: float = sig.get("price", sig.get("close", 0.0))

            # Estimate quantity (based on signal strength and portfolio cash)
            if price <= 0:
                rejected.append(f"{ticker}: invalid price")
                continue

            limit = 0.02
            breaker = getattr(self, "circuit_breaker", None)
            if breaker is not None and getattr(breaker, "single_order_limit", None):
                limit = float(breaker.single_order_limit)
            quantity: int = self._order_quantity(
                self.portfolio.cash,
                self.portfolio.total_value,
                signal_strength,
                price,
                single_order_limit=limit,
            )
            if quantity < 1:
                rejected.append(f"{ticker}: order smaller than 1 share under the single-order cap")
                continue

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
                try:
                    from shared.audit_trail import get_audit_trail

                    get_audit_trail().risk_reject(ticker, result.reason)
                except Exception:
                    pass
                if result.warnings:
                    for w in result.warnings:
                        logger.debug(f"    ⚠️ {ticker}: {w}")

        elapsed: float = time.time() - t0
        logger.info(
            f"  Step 4 ({elapsed:.1f}s): {len(approved)} passed / "
            f"{len(rejected)} rejected / {len(signals)} total"
        )
        if rejected:
            logger.info(f"    Rejection details: {rejected[:5]}{'...' if len(rejected) > 5 else ''}")

        return approved

    # ═══════════════════════════════════════════════════════════════
    # Step 5: Optimize Portfolio
    # ═══════════════════════════════════════════════════════════════

    async def _optimize_portfolio(self, signals: List[Dict]) -> Dict[str, float]:
        """HTTP → execution-service:8016 Black-Litterman portfolio optimization.

        POST /api/v2/execution/optimizer/bl
        Body: {"views": [...], "constraints": {...}}

        Args:
            signals: Approved signal list from Step 4.

        Returns:
            {ticker: target_weight, ...}
        """
        t0: float = time.time()
        if not self.config.ENABLE_PORTFOLIO_OPT:
            logger.info("  Step 5: portfolio optimization disabled — using equal-weight allocation")
            return self._equal_weight_fallback(signals)

        try:
            # Signals → BL views
            views: List[Dict] = signals_to_bl_views(signals)
            views = validate_views(views)

            if not views:
                logger.warning("Step 5: no valid BL views")
                return {}

            http = await self._get_http()
            payload: Dict = {
                "views": views,
                "tickers": [v["ticker"] for v in views],
                "constraints": {
                    "max_position_size": float(
                        getattr(self.risk_manager, "MAX_POSITION_SIZE", 0.35)
                    ),
                    "min_position_size": 0.0,
                    "max_turnover": 0.40,
                },
            }
            resp = await http.post(
                f"{self.service_urls['execution']}/api/v2/execution/optimizer/bl",
                json=payload,
            )

            if resp.status_code != 200:
                logger.warning(
                    f"BL optimizer returned {resp.status_code}: {resp.text[:200]}"
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
            logger.warning("Step 5 BL optimizer timed out — using equal-weight fallback")
            return self._equal_weight_fallback(signals)
        except Exception as e:
            logger.error(f"Step 5 failed: {e}")
            return self._equal_weight_fallback(signals)

    def _equal_weight_fallback(self, signals: List[Dict]) -> Dict[str, float]:
        """Equal-weight fallback — NAV-aware deploy fraction (not 20% cash park)."""
        if not signals:
            return {}
        try:
            from shared.capital_policy import build_capital_policy

            pol = build_capital_policy(self.portfolio.total_value)
            deploy = pol.deploy_frac
        except Exception:
            deploy = 0.80
        n: int = len(signals)
        weight: float = round(deploy / max(n, 1), 6)
        # Cap single name by max position
        try:
            max_pos = float(self.risk_manager.MAX_POSITION_SIZE)
        except Exception:
            max_pos = 0.35
        weight = min(weight, max_pos)
        return {s.get("ticker", ""): weight for s in signals if s.get("ticker")}

    # ═══════════════════════════════════════════════════════════════
    # Step 6: Execute Rebalance
    # ═══════════════════════════════════════════════════════════════

    async def _execute_rebalance(self, target_weights: Dict[str, float]) -> List[Dict]:
        """TigerExecutor unified rebalance execution.

        Use v2 TigerExecutor (live/paper strategy mode) to apply weight adjustments.
        Replaces the v1 PaperExecutor manual loop.

        Args:
            target_weights: {ticker: target_weight, ...} from Step 5.

        Returns:
            List of executed order records.
        """
        t0: float = time.time()
        if not target_weights:
            logger.info("  Step 6: no target weights, skipping execution")
            return []

        try:
            # Fetch live prices (HTTP first; fall back to signal-carried price)
            prices: Dict[str, float] = {}
            for ticker in target_weights:
                # Redis quote cache first
                try:
                    from shared.market_cache import sync_get_quote, sync_cache_quote

                    cached = sync_get_quote(ticker)
                    if cached and cached > 0:
                        prices[ticker] = cached
                        continue
                except Exception:
                    pass
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
                            try:
                                from shared.market_cache import sync_cache_quote

                                sync_cache_quote(ticker, px, source="data_service")
                            except Exception:
                                pass
                except Exception:
                    pass

            # Fallback: use last close from ParquetStore for prices
            if not prices:
                try:
                    from services.data_service.storage.parquet_store import ParquetStore
                    store = ParquetStore()
                    for ticker in target_weights:
                        df = store.read_daily(ticker)
                        if df is not None and len(df) > 0:
                            px = float(df["close"].iloc[-1])
                            if px > 0:
                                prices[ticker] = px
                except Exception:
                    pass

            if not prices:
                logger.warning("Step 6: no valid prices, skipping execution")
                return []

            # Delegate to TigerExecutor.execute_rebalance
            current_positions: Dict[str, float] = dict(self.portfolio.positions)
            block_buys = bool(getattr(self, "_block_buys", False))
            self.executor.block_buys = block_buys
            orders: List[Dict] = self.executor.execute_rebalance(
                target_weights=target_weights,
                prices=prices,
                current_positions=current_positions,
                block_buys=block_buys,
            )

            # Count non-rejected trades
            filled: int = sum(1 for o in orders if not o.get("rejected"))
            self.trades_today += filled

            elapsed: float = time.time() - t0
            rejected: int = len(orders) - filled
            logger.info(
                f"  Step 6 ({elapsed:.1f}s): {filled} fills"
                + (f", {rejected} rejected" if rejected else "")
            )

            # Persist state
            if orders:
                self.portfolio.save_state()

            return orders

        except Exception as e:
            logger.error(f"Step 6 execution failed: {e}")
            return []

    # ═══════════════════════════════════════════════════════════════
    # Step 7: Record Performance
    # ═══════════════════════════════════════════════════════════════

    async def _record_performance(self, orders: List[Dict]) -> None:
        """Performance recording — write cache/cycle_history.jsonl + optional PostgreSQL.

        Args:
            orders: Executed orders from Step 6.
        """
        t0: float = time.time()
        try:
            metrics: Dict = self.portfolio.get_metrics()

            logger.info(
                f"  Step 7 ({time.time() - t0:.1f}s): "
                f"total assets ${metrics.get('total_value', 0):,.0f} | "
                f"P&L {metrics.get('total_return_pct', 0):+.1f}% | "
                f"{metrics.get('num_positions', 0)} positions"
            )

            # Institutional audit trail
            try:
                from shared.audit_trail import get_audit_trail
                from shared.kill_switch import get_kill_switch

                get_audit_trail().cycle(
                    self.cycle_count,
                    self.trade_date,
                    orders=len(orders),
                    risk_snapshot={
                        **self.risk_manager.get_status(),
                        "kill_switch": get_kill_switch().status(),
                    },
                    extra={"metrics": metrics},
                )
                for o in orders:
                    get_audit_trail().order(o)
            except Exception as audit_exc:
                logger.debug(f"AuditTrail skipped: {audit_exc}")

            # ── CycleSummary persist to cache/cycle_history.jsonl (append) ──
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

            # PostgreSQL CyclePerformance table is optional; JSONL is source of truth.
            # (Previously imported non-existent shared.database.models.CyclePerformance.)

        except Exception as e:
            logger.error(f"Step 7 performance recording error: {e}")

    # ═══════════════════════════════════════════════════════════════
    # DB Write Helpers — write signals/trades to the SQLite database
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
            logger.debug(f"  📊 signals → DB: {written} rows written to signals table")
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
            logger.debug(f"  📈 trades → DB: {written} fills written to trades table")
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
        """Exponential-backoff retry for HTTP calls.

        Automatically retry when a v2 service is unavailable; return None
        after all attempts fail so the caller can use the v1 fallback.

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
        """Force-liquidate holdings in FORCE_SELL_TICKERS on startup.

        Iterate config.FORCE_SELL_TICKERS and issue a market sell for each
        open position. Paper mode updates local state only; live mode
        also places the order through Tiger.
        """
        positions: Dict[str, float] = dict(self.portfolio.positions)
        for ticker in self.config.FORCE_SELL_TICKERS:
            if ticker in positions and positions[ticker] != 0.0:
                shares: float = abs(positions[ticker])
                logger.warning(f"🔴 Force-sell: {ticker} × {shares} shares")

                try:
                    if self.tiger_ready:
                        self.tiger.place_order(
                            ticker=ticker,
                            action="SELL",
                            quantity=int(shares),
                            order_type="MKT",
                        )
                except Exception as exc:
                    logger.warning(f"Force-sell Tiger order error {ticker}: {exc}")

                # Update local state.
                self.portfolio.execute_trade(
                    ticker=ticker,
                    side="sell",
                    price=0.0,  # Market order — exact fill unknown.
                    quantity=shares,
                    strategy="force_sell",
                )
                logger.info(f"  ✅ Force-sell complete: {ticker} × {shares}")

    # ═══════════════════════════════════════════════════════════════
    # P2-1: Git Auto-Sync
    # ═══════════════════════════════════════════════════════════════

    def _git_sync(self) -> None:
        """Trigger one git add/commit/pull/push.

        Runs via ``shared.git_sync.git_sync``; all exceptions are silently
        degraded so they never block the trading loop.
        """
        logger.info("🔄 Git auto-sync...")
        ok: bool = git_sync(str(Path(__file__).resolve().parent))
        if ok:
            logger.debug("Git sync succeeded")
        else:
            logger.debug("Git sync skipped or failed (see debug log)")


# ═══════════════════════════════════════════════════════════════
# CLI entry point
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
        help="Cycle interval in seconds; default 300 (5 minutes)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one trading cycle then exit (for development/testing)",
    )
    args = parser.parse_args()

    pipeline = TradingPipeline(config=pipeline_config)

    async def _main() -> None:
        try:
            if args.once:
                logger.info("🚀 Single-run mode (--once)")
                result = await pipeline.run_cycle()
                if result:
                    logger.info(f"✅ Single run complete: {result}")
                else:
                    logger.warning("⚠️ Single run returned no result (possibly insufficient data)")
            else:
                await pipeline.run(interval_seconds=args.interval)
        finally:
            await pipeline.close()

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        logger.info("⏹ Trading Pipeline received shutdown signal")
        sys.exit(0)
