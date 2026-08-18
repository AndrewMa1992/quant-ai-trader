"""
Risk Gate — 交易管线风控统一入口
=================================
下单前统一过闸（机构级）：
0. KillSwitch — 持久化紧急停机
1. CircuitBreaker.allow_order() — 熔断器
2. Barra 因子暴露检查 — 不超过 BARRA_EXPOSURE_MAX_Z
3. VaR 检查 — 日 VaR < VAR_LIMIT_PCT × 组合价值
4. CVaR 检查 — CVaR < CVAR_LIMIT_PCT × 组合价值
5. Gross / Net / Single exposure — RISK_LIMITS
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import httpx
from loguru import logger

from configs.pipeline_config import pipeline_config


@dataclass
class RiskResult:
    """风控检查结果"""
    passed: bool
    reason: str
    warnings: List[str] = field(default_factory=list)
    sanitized_weights: Optional[Dict[str, float]] = None


class RiskGate:
    """风控统一入口（KillSwitch + CB + Barra + VaR + CVaR + Exposure）。

    依赖:
        - circuit_breaker: services.execution_service.monitor.circuit_breaker.CircuitBreaker
        - risk_service_url: risk-service (8015) 的 base URL
        - constraints: dict of constraint parameters
    """

    def __init__(
        self,
        circuit_breaker,               # CircuitBreaker instance
        risk_service_url: str,
        constraints: Optional[Dict] = None,
    ):
        self.cb = circuit_breaker
        self.risk_url: str = risk_service_url.rstrip("/")
        self.constraints: Dict = constraints or {}
        self._http_client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy init httpx AsyncClient."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(pipeline_config.HTTP_TIMEOUT),
            )
        return self._http_client

    async def close(self) -> None:
        """Clean up HTTP client."""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    # ── Public API ─────────────────────────────────────────────────

    async def check(
        self,
        ticker: str,
        quantity: int,
        price: float,
        portfolio_state: Dict,
        signal_strength: float,
    ) -> RiskResult:
        """依次执行四道风控检查。

        Args:
            ticker: 股票代码
            quantity: 拟交易股数
            price: 拟交易价格
            portfolio_state: 组合快照 {total_value, cash, positions, ...}
            signal_strength: 信号强度 ∈ [-1, 1]

        Returns:
            RiskResult: 全部通过 → passed=True
                        任一不通过 → passed=False + reason
        """
        order_value: float = quantity * price
        warnings: List[str] = []

        # ── Gate 0: Durable kill switch (always first) ─────
        try:
            from shared.kill_switch import get_kill_switch

            if get_kill_switch().engaged:
                return RiskResult(
                    passed=False,
                    reason="KillSwitch: trading halted until operator reset",
                    warnings=warnings,
                )
        except Exception as e:
            fail = self._on_check_failure(f"KillSwitch check error: {e}")
            if not fail["passed"]:
                return RiskResult(passed=False, reason=fail["reason"], warnings=warnings)
            if fail.get("warning"):
                warnings.append(fail["warning"])

        # ── Gate 1: CircuitBreaker ──────────────────────────
        cb_result = await self._check_circuit_breaker(ticker, quantity, price)
        if not cb_result["passed"]:
            return RiskResult(
                passed=False,
                reason=f"CircuitBreaker: {cb_result['reason']}",
                warnings=warnings,
            )
        if cb_result.get("warning"):
            warnings.append(cb_result["warning"])

        # ── Gate 2: Barra Factor Exposure ───────────────────
        barra_result = await self._check_barra_exposure(portfolio_state)
        if not barra_result["passed"]:
            return RiskResult(
                passed=False,
                reason=f"BarraExposure: {barra_result['reason']}",
                warnings=warnings,
            )
        if barra_result.get("warning"):
            warnings.append(barra_result["warning"])

        # ── Gate 3: VaR ─────────────────────────────────────
        var_result = await self._check_var(
            ticker, order_value, portfolio_state
        )
        if not var_result["passed"]:
            return RiskResult(
                passed=False,
                reason=f"VaR: {var_result['reason']}",
                warnings=warnings,
            )
        if var_result.get("warning"):
            warnings.append(var_result["warning"])

        # ── Gate 4: CVaR ────────────────────────────────────
        cvar_result = await self._check_cvar(
            ticker, order_value, portfolio_state
        )
        if not cvar_result["passed"]:
            return RiskResult(
                passed=False,
                reason=f"CVaR: {cvar_result['reason']}",
                warnings=warnings,
            )
        if cvar_result.get("warning"):
            warnings.append(cvar_result["warning"])

        # ── Gate 5: Gross / Net / Position exposure (local, always-on) ──
        exposure_result = self._check_exposures(
            ticker, quantity, price, portfolio_state
        )
        if not exposure_result["passed"]:
            return RiskResult(
                passed=False,
                reason=f"Exposure: {exposure_result['reason']}",
                warnings=warnings,
            )
        if exposure_result.get("warning"):
            warnings.append(exposure_result["warning"])

        # 全部通过
        if warnings:
            logger.info(
                f"✅ RiskGate 通过 ({ticker}) | "
                f"警告 {len(warnings)}: {warnings}"
            )
        return RiskResult(passed=True, reason="ALL_PASSED", warnings=warnings)

    # ── Gate Implementations ──────────────────────────────────────

    async def _check_circuit_breaker(
        self, ticker: str, quantity: int, price: float
    ) -> Dict:
        """Gate 1: 熔断器检查。

        Calls CircuitBreaker.allow_order() if available.
        """
        if not pipeline_config.ENABLE_RISK_CHECKS:
            return {"passed": True}

        try:
            if hasattr(self.cb, "allow_order"):
                allowed: bool = self.cb.allow_order(ticker, quantity, price)
                if not allowed:
                    return {
                        "passed": False,
                        "reason": "Circuit breaker has tripped — all orders blocked",
                    }
                return {"passed": True}

            # Fallback: check basic breaker state
            if hasattr(self.cb, "is_tripped") and self.cb.is_tripped():
                return {
                    "passed": False,
                    "reason": "Circuit breaker is tripped",
                }
            return {"passed": True}

        except Exception as e:
            logger.warning(f"CircuitBreaker check error: {e}")
            return self._on_check_failure(f"CircuitBreaker error: {e}")

    def _fail_closed(self) -> bool:
        """Live trading must fail closed when risk checks are unavailable."""
        return str(pipeline_config.EXECUTION_MODE).lower() == "live"

    def _on_check_failure(self, reason: str) -> Dict:
        """Fail closed in live mode; warn-and-pass in paper mode."""
        if self._fail_closed():
            return {"passed": False, "reason": f"{reason} (fail-closed live mode)"}
        return {"passed": True, "warning": f"{reason} (failing open paper mode)"}

    def _portfolio_tickers_weights(self, portfolio_state: Dict) -> tuple[str, str]:
        """Build comma-separated tickers/weights for risk-service queries."""
        positions = portfolio_state.get("positions") or {}
        total_value = float(portfolio_state.get("total_value") or 0.0)
        if not isinstance(positions, dict) or not positions:
            return "SPY", "1.0"

        tickers: List[str] = []
        weights: List[float] = []
        for ticker, shares in positions.items():
            try:
                qty = float(shares)
            except (TypeError, ValueError):
                continue
            if qty == 0:
                continue
            # Prefer explicit market values when present
            pos_values = portfolio_state.get("position_values") or {}
            mv = float(pos_values.get(ticker, 0.0) or 0.0)
            if mv <= 0 and total_value > 0:
                # Fallback equal weight among held names
                continue
            tickers.append(str(ticker))
            weights.append(max(mv, 0.0))

        if not tickers:
            tickers = [str(t) for t, s in positions.items() if float(s or 0) != 0][:20] or ["SPY"]
            n = len(tickers)
            return ",".join(tickers), ",".join(str(1.0 / n) for _ in tickers)

        weight_sum = sum(weights) or 1.0
        norm = [w / weight_sum for w in weights]
        return ",".join(tickers), ",".join(f"{w:.6f}" for w in norm)

    async def _check_barra_exposure(self, portfolio_state: Dict) -> Dict:
        """Gate 2: Barra 因子暴露检查。

        Fetches current exposures from risk-service and checks
        that no factor Z-score exceeds BARRA_EXPOSURE_MAX_Z.
        """
        if not pipeline_config.ENABLE_RISK_CHECKS:
            return {"passed": True}

        try:
            client = await self._get_client()
            tickers_csv, _weights = self._portfolio_tickers_weights(portfolio_state)
            sample_ticker = tickers_csv.split(",")[0] if tickers_csv else "SPY"
            resp = await client.get(
                f"{self.risk_url}/api/v2/risk/barra/exposure",
                params={"ticker": sample_ticker},
            )

            if resp.status_code != 200:
                return self._on_check_failure(
                    f"Barra exposure fetch failed (HTTP {resp.status_code})"
                )

            data = resp.json()
            payload: Dict = data.get("data", data)
            exposures: Dict = payload.get("exposures", payload)

            max_z: float = 0.0
            max_factor: str = ""
            for factor_name, z_score in exposures.items():
                if isinstance(z_score, (int, float)):
                    if abs(z_score) > max_z:
                        max_z = abs(z_score)
                        max_factor = factor_name

            if max_z > pipeline_config.BARRA_EXPOSURE_MAX_Z:
                return {
                    "passed": False,
                    "reason": (
                        f"Factor '{max_factor}' Z-score={max_z:.2f} exceeds "
                        f"limit {pipeline_config.BARRA_EXPOSURE_MAX_Z}"
                    ),
                }

            return {"passed": True}

        except httpx.TimeoutException:
            logger.warning("Barra exposure check timed out")
            return self._on_check_failure("Barra exposure check timed out")
        except Exception as e:
            logger.warning(f"Barra exposure check error: {e}")
            return self._on_check_failure(f"Barra exposure check error: {e}")

    async def _check_var(
        self,
        ticker: str,
        order_value: float,
        portfolio_state: Dict,
    ) -> Dict:
        """Gate 3: VaR 检查。

        GET risk-service:/api/v2/risk/var
        校验日 VaR < VAR_LIMIT_PCT × portfolio_value
        """
        if not pipeline_config.ENABLE_RISK_CHECKS:
            return {"passed": True}

        try:
            client = await self._get_client()
            portfolio_value: float = portfolio_state.get("total_value", 0.0)
            tickers_csv, weights_csv = self._portfolio_tickers_weights(portfolio_state)
            params: Dict = {
                "confidence": pipeline_config.VAR_CONFIDENCE,
                "tickers": tickers_csv,
                "weights": weights_csv,
            }
            resp = await client.get(
                f"{self.risk_url}/api/v2/risk/var",
                params=params,
            )

            if resp.status_code != 200:
                return self._on_check_failure(
                    f"VaR fetch failed (HTTP {resp.status_code})"
                )

            data = resp.json()
            var_data: Dict = data.get("data", data)
            var_value: float = float(var_data.get("var", var_data.get("var_95", 0.0)))

            var_limit: float = pipeline_config.VAR_LIMIT_PCT * portfolio_value

            if var_value > var_limit:
                return {
                    "passed": False,
                    "reason": (
                        f"VaR ${var_value:,.2f} ({var_value / max(portfolio_value, 1) * 100:.2f}%) "
                        f"exceeds limit ${var_limit:,.2f} ({pipeline_config.VAR_LIMIT_PCT * 100:.1f}%)"
                    ),
                }

            return {"passed": True}

        except httpx.TimeoutException:
            logger.warning("VaR check timed out")
            return self._on_check_failure("VaR check timed out")
        except Exception as e:
            logger.warning(f"VaR check error: {e}")
            return self._on_check_failure(f"VaR check error: {e}")

    async def _check_cvar(
        self,
        ticker: str,
        order_value: float,
        portfolio_state: Dict,
    ) -> Dict:
        """Gate 4: CVaR 检查。

        GET risk-service:/api/v2/risk/cvar
        校验 CVaR < CVAR_LIMIT_PCT × portfolio_value
        """
        if not pipeline_config.ENABLE_RISK_CHECKS:
            return {"passed": True}

        try:
            client = await self._get_client()
            portfolio_value: float = portfolio_state.get("total_value", 0.0)
            tickers_csv, weights_csv = self._portfolio_tickers_weights(portfolio_state)
            params: Dict = {
                "confidence": pipeline_config.VAR_CONFIDENCE,
                "tickers": tickers_csv,
                "weights": weights_csv,
            }
            resp = await client.get(
                f"{self.risk_url}/api/v2/risk/cvar",
                params=params,
            )

            if resp.status_code != 200:
                return self._on_check_failure(
                    f"CVaR fetch failed (HTTP {resp.status_code})"
                )

            data = resp.json()
            risk_data: Dict = data.get("data", data)
            cvar_value: float = float(risk_data.get("cvar", risk_data.get("cvar_95", 0.0)))

            cvar_limit: float = pipeline_config.CVAR_LIMIT_PCT * portfolio_value

            if cvar_value > cvar_limit:
                return {
                    "passed": False,
                    "reason": (
                        f"CVaR ${cvar_value:,.2f} ({cvar_value / max(portfolio_value, 1) * 100:.2f}%) "
                        f"exceeds limit ${cvar_limit:,.2f} ({pipeline_config.CVAR_LIMIT_PCT * 100:.1f}%)"
                    ),
                }

            return {"passed": True}

        except httpx.TimeoutException:
            logger.warning("CVaR check timed out")
            return self._on_check_failure("CVaR check timed out")
        except Exception as e:
            logger.warning(f"CVaR check error: {e}")
            return self._on_check_failure(f"CVaR check error: {e}")

    def _check_exposures(
        self,
        ticker: str,
        quantity: int,
        price: float,
        portfolio_state: Dict,
    ) -> Dict:
        """Gate 5: gross / net / single-name exposure vs RISK_LIMITS."""
        if not pipeline_config.ENABLE_RISK_CHECKS:
            return {"passed": True}

        try:
            from configs.risk_limits import RISK_LIMITS

            nav = float(portfolio_state.get("total_value") or 0.0)
            if nav <= 0:
                return {"passed": True, "warning": "NAV unknown — exposure check skipped"}

            pos_values = dict(portfolio_state.get("position_values") or {})
            # Project post-trade market value for this ticker
            side_sign = 1.0 if quantity >= 0 else -1.0
            # quantity is absolute shares for buy intent in pipeline; treat as buy notional add
            delta = abs(quantity) * price * side_sign
            current_mv = float(pos_values.get(ticker, 0.0) or 0.0)
            pos_values[ticker] = current_mv + delta

            gross = sum(abs(v) for v in pos_values.values()) / nav
            net = sum(pos_values.values()) / nav
            single = abs(pos_values.get(ticker, 0.0)) / nav

            if single > RISK_LIMITS.MAX_SINGLE_STOCK_EXPOSURE:
                return {
                    "passed": False,
                    "reason": (
                        f"{ticker} weight {single:.2%} > "
                        f"MAX_SINGLE_STOCK_EXPOSURE {RISK_LIMITS.MAX_SINGLE_STOCK_EXPOSURE:.0%}"
                    ),
                }
            if gross > RISK_LIMITS.MAX_GROSS_EXPOSURE:
                return {
                    "passed": False,
                    "reason": (
                        f"gross exposure {gross:.2%} > "
                        f"MAX_GROSS_EXPOSURE {RISK_LIMITS.MAX_GROSS_EXPOSURE:.2f}"
                    ),
                }
            if abs(net) > RISK_LIMITS.MAX_NET_EXPOSURE:
                return {
                    "passed": False,
                    "reason": (
                        f"net exposure {net:.2%} > "
                        f"MAX_NET_EXPOSURE {RISK_LIMITS.MAX_NET_EXPOSURE:.2f}"
                    ),
                }
            return {"passed": True}
        except Exception as e:
            return self._on_check_failure(f"Exposure check error: {e}")
