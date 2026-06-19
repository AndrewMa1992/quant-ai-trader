"""
Trading Pipeline — v2 核心交易编排器
=====================================
替代 v1 auto_trader.py，串联六微服务执行 T+0 交易周期。

七步流程:
  0. Get Active Universe — 获取当日活跃股票池
  1. Fetch Market Data — HTTP → data-service:8011
  2. Compute Factors — 本地 FactorEngine
  3. Run Inference — 本地 InferenceEngine
  4. Apply Risk Checks — RiskGate（四道风控）
  5. Optimize Portfolio — HTTP → execution-service:8016 BL optimizer
  6. Execute Rebalance — TigerBroker + TWAP/VWAP
  7. Record Performance — 写入 shared database
"""
import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import httpx
from loguru import logger

from configs.pipeline_config import PipelineConfig, pipeline_config
from shared.risk_gate import RiskGate, RiskResult
from shared.signal_to_views import signals_to_bl_views, validate_views

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

# ── v1 → v2 桥接（v1 模块保留用于过渡） ─────────────────────
from backend.data_engine.tiger_client import tiger_client as _tiger_client
from backend.trading_engine.portfolio import PortfolioManager
from backend.trading_engine.risk_manager import RiskManager


class TradingPipeline:
    """v2 核心交易编排器。

    七步串联 v2 微服务管线，替代 v1 auto_trader.py。
    每步独立 try/except，单步失败不中断整轮循环。
    """

    def __init__(self, config: PipelineConfig) -> None:
        self.config: PipelineConfig = config
        self.service_urls: Dict[str, str] = config.SERVICE_BASE_URLS

        # ── 本地引擎（v2 已有，导入失败时降级为 stub） ──────
        logger.info("初始化本地引擎...")
        if FactorEngine is not None:
            self.factor_engine: FactorEngine = FactorEngine()
            logger.info("  ✅ FactorEngine 已就绪")
        else:
            self.factor_engine = None  # type: ignore[assignment]
            logger.warning("  ⚠️ FactorEngine 不可用 — stub 模式")

        if InferenceEngine is not None:
            self.inference_engine: InferenceEngine = InferenceEngine()
            logger.info("  ✅ InferenceEngine 已就绪")
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

        # ── 交易组件 ─────────────────────────────────────────
        logger.info("初始化交易组件...")
        self.portfolio: PortfolioManager = PortfolioManager()
        self.risk_manager: RiskManager = RiskManager()
        self.position_tracker = self.portfolio  # alias for backward compat

        # Tiger 连接
        self.tiger_ready: bool = _tiger_client.connect()
        if self.tiger_ready:
            logger.info("  ✅ Tiger Broker 已连接")
        else:
            logger.warning("  ⚠️ Tiger Broker 未连接 — Paper Trading 模式")

        self.tiger_broker = _tiger_client  # alias

        # ── 数据目录 ─────────────────────────────────────────
        self.data_dir: Path = Path("data/daily")
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # ── HTTP 客户端 ──────────────────────────────────────
        self._http: Optional[httpx.AsyncClient] = None

        # ── 状态 ────────────────────────────────────────────
        self.cycle_count: int = 0
        self.trades_today: int = 0
        self.trade_date: str = datetime.now().strftime("%Y-%m-%d")

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

    # ═══════════════════════════════════════════════════════════════
    # Main Loop
    # ═══════════════════════════════════════════════════════════════

    async def run(self, interval_seconds: int = 300) -> None:
        """主循环：每隔 interval_seconds 秒运行一个交易周期。

        Args:
            interval_seconds: 循环间隔，默认 300s (5 min)
        """
        logger.info(f"🚀 交易管线启动 — 间隔 {interval_seconds}s")
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

        # ── 日期切换检测 ────────────────────────────────────
        today: str = datetime.now().strftime("%Y-%m-%d")
        if today != self.trade_date:
            self.trades_today = 0
            self.trade_date = today
            logger.info(f"📅 新交易日 {today}，重置交易计数")

        logger.info(
            f"\n{'=' * 50}\n"
            f"  Cycle #{self.cycle_count} — {datetime.now().strftime('%H:%M:%S')}\n"
            f"{'=' * 50}"
        )

        # Step 0: Get Active Universe
        tickers: List[str] = await self._get_active_universe()
        if not tickers:
            logger.warning("活跃股票池为空，跳过本轮")
            return None
        logger.info(f"Step 0: 股票池 {len(tickers)} 只")

        # Step 1: Fetch Market Data
        data: Dict = await self._fetch_market_data(tickers)
        if not data or len(data) < 2:
            logger.warning("市场数据不足，跳过本轮")
            return None

        # Step 2: Compute Factors
        factor_df = await self._compute_factors(data)

        # Step 3: Run Inference
        signals: List[Dict] = await self._run_inference(factor_df, tickers)
        if not signals:
            logger.warning("无有效信号，跳过本轮")
            return None

        # Step 4: Apply Risk Checks
        approved: List[Dict] = await self._apply_risk_checks(signals)

        # Step 5: Optimize Portfolio
        target_weights: Dict = await self._optimize_portfolio(approved)

        # Step 6: Execute Rebalance
        orders: List[Dict] = await self._execute_rebalance(target_weights)

        # Step 7: Record Performance
        await self._record_performance(orders)

        # ── 周期汇总 ─────────────────────────────────────────
        elapsed: float = time.time() - t_start
        logger.info(
            f"⏱  Cycle #{self.cycle_count} 完成 "
            f"| 耗时 {elapsed:.1f}s "
            f"| 信号 {len(signals)} → 通过 {len(approved)} → 订单 {len(orders)}"
        )

        return {
            "cycle": self.cycle_count,
            "timestamp": datetime.now().isoformat(),
            "tickers": len(tickers),
            "signals": len(signals),
            "approved": len(approved),
            "orders": len(orders),
            "elapsed_seconds": round(elapsed, 2),
        }

    # ═══════════════════════════════════════════════════════════════
    # Step 0: Get Active Universe
    # ═══════════════════════════════════════════════════════════════

    async def _get_active_universe(self) -> List[str]:
        """获取当日活跃股票池。

        Returns:
            List of ticker strings, capped at MAX_TICKERS_PER_CYCLE.
        """
        t0: float = time.time()
        try:
            # v2: 从 data-service 获取股票池
            http = await self._get_http()
            resp = await http.get(
                f"{self.service_urls['data']}/api/v2/data/symbols",
                params={"active": "true"},
            )
            if resp.status_code == 200:
                data = resp.json()
                symbols_data = data.get("data", data)
                if isinstance(symbols_data, list):
                    tickers = [
                        (s.get("symbol") or s.get("ticker") or "")
                        for s in symbols_data
                    ]
                elif isinstance(symbols_data, dict):
                    tickers = list(symbols_data.keys())
                else:
                    tickers = []
            else:
                logger.warning(f"data-service symbols 返回 {resp.status_code}")
                tickers = []
        except Exception as e:
            logger.warning(f"获取股票池失败: {e}，使用 v1 fallback")
            tickers = self._get_active_universe_v1_fallback()

        # 过滤并限制数量
        tickers = [t for t in tickers if isinstance(t, str) and t]
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
        """HTTP → data-service:8011 获取市场数据。

        GET /api/v2/data/bars?tickers=AAPL,MSFT,...

        Returns:
            {ticker: {prices: [...], volumes: [...], ...}, ...}
        """
        t0: float = time.time()
        try:
            http = await self._get_http()
            tickers_param: str = ",".join(tickers)
            resp = await http.get(
                f"{self.service_urls['data']}/api/v2/data/bars",
                params={"tickers": tickers_param},
            )

            if resp.status_code != 200:
                logger.warning(f"data-service bars 返回 {resp.status_code}")
                return self._fetch_market_data_v1_fallback(tickers)

            data = resp.json()
            result: Dict = data.get("data", data)
            elapsed: float = time.time() - t0
            count: int = len(result) if isinstance(result, dict) else 0
            logger.info(f"  Step 1 ({elapsed:.1f}s): {count}/{len(tickers)} 成功")
            return result if isinstance(result, dict) else {}

        except httpx.TimeoutException:
            logger.warning("Step 1 超时 — 使用 v1 fallback")
            return self._fetch_market_data_v1_fallback(tickers)
        except Exception as e:
            logger.warning(f"Step 1 失败: {e}")
            return self._fetch_market_data_v1_fallback(tickers)

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
        if self.factor_engine is None:
            logger.warning("  Step 2: FactorEngine stub — returning empty DataFrame")
            import pandas as pd
            return pd.DataFrame({"ticker": list(data.keys())})

        try:
            # v2 FactorEngine.compute_all_multi accepts dict of data
            factor_df = self.factor_engine.compute_all_multi(data)
            elapsed: float = time.time() - t0
            n_factors: int = factor_df.shape[1] if hasattr(factor_df, "shape") else 0
            n_tickers: int = factor_df.shape[0] if hasattr(factor_df, "shape") else 0
            logger.info(f"  Step 2 ({elapsed:.1f}s): {n_tickers} tickers × {n_factors} factors")
            return factor_df
        except Exception as e:
            logger.error(f"Step 2 因子计算失败: {e}")
            import pandas as pd
            return pd.DataFrame({"ticker": list(data.keys())})

    # ═══════════════════════════════════════════════════════════════
    # Step 3: Run Inference
    # ═══════════════════════════════════════════════════════════════

    async def _run_inference(self, factor_df, tickers: List[str]) -> List[Dict]:
        """本地 InferenceEngine 模型推理。

        Args:
            factor_df: Factor DataFrame from Step 2.
            tickers: Active ticker list.

        Returns:
            List of signal dicts: [{"ticker": "AAPL", "signal": 0.6, "confidence": 0.8}, ...]
        """
        t0: float = time.time()
        if self.inference_engine is None:
            logger.warning("  Step 3: InferenceEngine stub — returning HOLD for all tickers")
            return [
                {"ticker": t, "signal": 0.0, "confidence": 0.0, "direction": "HOLD"}
                for t in tickers
            ]

        try:
            # v2 InferenceEngine.generate_signals_batch returns signals
            signals: List[Dict] = self.inference_engine.generate_signals_batch(factor_df)

            elapsed: float = time.time() - t0
            valid: List[Dict] = [
                s for s in signals
                if isinstance(s, dict)
                and abs(s.get("signal", s.get("strength", 0.0))) >= self.config.SIGNAL_THRESHOLD
                and s.get("confidence", 0.0) >= self.config.MIN_CONFIDENCE
            ]
            logger.info(
                f"  Step 3 ({elapsed:.1f}s): {len(signals)} raw → "
                f"{len(valid)} above threshold ({self.config.SIGNAL_THRESHOLD})"
            )
            return valid
        except Exception as e:
            logger.error(f"Step 3 推理失败: {e}")
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
        """TigerBroker + TWAP/VWAP 执行再平衡。

        比对新旧权重，生成买卖订单并通过 Tiger Broker 执行。

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
            from backend.trading_engine.executor import PaperExecutor

            executor: PaperExecutor = PaperExecutor(
                portfolio=self.portfolio,
                risk_manager=self.risk_manager,
            )

            orders: List[Dict] = []
            current_positions: Dict[str, float] = dict(self.portfolio.positions)
            total_value: float = self.portfolio.total_value

            for ticker, target_weight in target_weights.items():
                try:
                    current_shares: float = current_positions.get(ticker, 0.0)
                    current_value: float = current_shares * self.portfolio.avg_costs.get(
                        ticker, 0.0
                    )
                    current_weight: float = current_value / max(total_value, 1.0)
                    diff: float = target_weight - current_weight

                    # 差异小于 0.5% 不调
                    if abs(diff) < 0.005:
                        continue

                    # 获取价格
                    price: float = 0.0
                    try:
                        http = await self._get_http()
                        resp = await http.get(
                            f"{self.service_urls['data']}/api/v2/data/realtime/{ticker}"
                        )
                        if resp.status_code == 200:
                            rt = resp.json()
                            rt_data = rt.get("data", rt)
                            price = float(rt_data.get("price", rt_data.get("close", 0.0)))
                    except Exception:
                        price = 0.0

                    if price <= 0:
                        continue

                    decision: str = "buy" if diff > 0 else "sell"
                    strength: float = min(abs(diff), 0.20)
                    confidence: float = 0.6  # moderate confidence for rebalance

                    order: Optional[Dict] = executor.execute_signal(
                        ticker=ticker,
                        decision=decision,
                        strength=strength,
                        price=price,
                        confidence=confidence,
                        strategy="bl_rebalance",
                    )
                    if order:
                        orders.append(order)
                        self.trades_today += 1

                except Exception as e:
                    logger.warning(f"Step 6 单票执行异常 {ticker}: {e}")
                    continue

            # 保存状态
            if orders:
                self.portfolio.save_state()

            elapsed: float = time.time() - t0
            logger.info(f"  Step 6 ({elapsed:.1f}s): {len(orders)} 笔成交")
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
