"""
Risk Gate — 交易管线风控统一入口
=================================
封装四道风控检查，下单前统一过闸：
1. CircuitBreaker.allow_order() — 熔断器
2. Barra 因子暴露检查 — 不超过 BARRA_EXPOSURE_MAX_Z
3. VaR 检查 — 日 VaR < VAR_LIMIT_PCT × 组合价值
4. CVaR 检查 — CVaR < CVAR_LIMIT_PCT × 组合价值
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
    """风控统一入口，封装四道检查。

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
            # Fail open on error (don't block trading due to breaker bug)
            return {
                "passed": True,
                "warning": f"CircuitBreaker error (failing open): {e}",
            }

    async def _check_barra_exposure(self, portfolio_state: Dict) -> Dict:
        """Gate 2: Barra 因子暴露检查。

        Fetches current exposures from risk-service and checks
        that no factor Z-score exceeds BARRA_EXPOSURE_MAX_Z.
        """
        if not pipeline_config.ENABLE_RISK_CHECKS:
            return {"passed": True}

        try:
            client = await self._get_client()
            resp = await client.get(f"{self.risk_url}/api/v2/risk/exposures")

            if resp.status_code != 200:
                return {
                    "passed": True,
                    "warning": f"Barra exposure fetch failed (HTTP {resp.status_code}) — skipping",
                }

            data = resp.json()
            exposures: Dict = data.get("data", data)

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
            logger.warning("Barra exposure check timed out — skipping")
            return {"passed": True, "warning": "Barra exposure check timed out"}
        except Exception as e:
            logger.warning(f"Barra exposure check error: {e}")
            return {"passed": True, "warning": f"Barra exposure check error: {e}"}

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
            params: Dict = {
                "confidence": pipeline_config.VAR_CONFIDENCE,
            }
            resp = await client.get(
                f"{self.risk_url}/api/v2/risk/var",
                params=params,
            )

            if resp.status_code != 200:
                return {
                    "passed": True,
                    "warning": f"VaR fetch failed (HTTP {resp.status_code}) — skipping",
                }

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
            logger.warning("VaR check timed out — skipping")
            return {"passed": True, "warning": "VaR check timed out"}
        except Exception as e:
            logger.warning(f"VaR check error: {e}")
            return {"passed": True, "warning": f"VaR check error: {e}"}

    async def _check_cvar(
        self,
        ticker: str,
        order_value: float,
        portfolio_state: Dict,
    ) -> Dict:
        """Gate 4: CVaR 检查。

        GET risk-service:/api/v2/risk/var (same endpoint returns CVaR)
        校验 CVaR < CVAR_LIMIT_PCT × portfolio_value
        """
        if not pipeline_config.ENABLE_RISK_CHECKS:
            return {"passed": True}

        try:
            client = await self._get_client()
            portfolio_value: float = portfolio_state.get("total_value", 0.0)
            params: Dict = {
                "confidence": pipeline_config.VAR_CONFIDENCE,
            }
            resp = await client.get(
                f"{self.risk_url}/api/v2/risk/var",
                params=params,
            )

            if resp.status_code != 200:
                return {
                    "passed": True,
                    "warning": f"CVaR fetch failed (HTTP {resp.status_code}) — skipping",
                }

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
            logger.warning("CVaR check timed out — skipping")
            return {"passed": True, "warning": "CVaR check timed out"}
        except Exception as e:
            logger.warning(f"CVaR check error: {e}")
            return {"passed": True, "warning": f"CVaR check error: {e}"}
