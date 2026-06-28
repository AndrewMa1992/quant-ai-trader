"""
WsPusher — lightweight WebSocket / REST step-update pusher
===========================================================
Pushes per-step status updates and alerts to a front-end
dashboard.  Gracefully degrades when the push endpoint is
unreachable — never blocks the main pipeline.

Zero ``import backend.`` — uses plain ``httpx`` for HTTP push.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import httpx
from loguru import logger

# Default push endpoint (relative to api_url).
_DEFAULT_PUSH_PATH: str = "/api/v2/pipeline/step-update"


class WsPusher:
    """Non-blocking step-update / alert pusher.

    Typical usage (inside an async pipeline step)::

        await pusher.push_step_update(42, 4, {
            "approved": 5, "rejected": 2, "total": 7,
        })

    If the push endpoint returns a non-2xx or times out, the
    error is logged at DEBUG level and the pipeline continues.
    """

    def __init__(
        self,
        api_url: str = "",
        enabled: bool = True,
        timeout: float = 3.0,
    ) -> None:
        self.api_url: str = api_url.rstrip("/") if api_url else ""
        self.enabled: bool = enabled
        self.timeout: float = timeout
        self._http: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> Optional[httpx.AsyncClient]:
        """Lazy-init the HTTP client."""
        if not self.enabled or not self.api_url:
            return None
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout))
        return self._http

    async def push_step_update(
        self,
        cycle: int,
        step: int,
        data: Dict[str, Any],
    ) -> None:
        """Push a step-completion update to the dashboard.

        Args:
            cycle: Current pipeline cycle number.
            step: Step number (0-7).
            data: Arbitrary step-specific payload (e.g. ``{"tickers": 15}``).
        """
        client = await self._get_client()
        if client is None:
            return

        payload: Dict[str, Any] = {
            "cycle": cycle,
            "step": step,
            "data": data,
        }
        try:
            resp = await client.post(
                f"{self.api_url}{_DEFAULT_PUSH_PATH}",
                json=payload,
            )
            if resp.status_code >= 400:
                logger.debug(
                    f"WsPusher: step {step} push returned {resp.status_code}"
                )
        except httpx.TimeoutException:
            logger.debug(f"WsPusher: step {step} push timed out")
        except Exception as exc:
            logger.debug(f"WsPusher: step {step} push failed — {exc}")

    async def push_alert(self, alert_type: str, message: str) -> None:
        """Push a high-priority alert (e.g. circuit breaker).

        Args:
            alert_type: Short label (``"circuit_breaker"``, ``"leverage"``).
            message: Human-readable description.
        """
        client = await self._get_client()
        if client is None:
            return

        payload: Dict[str, Any] = {
            "type": "alert",
            "alert_type": alert_type,
            "message": message,
        }
        try:
            resp = await client.post(
                f"{self.api_url}/api/v2/pipeline/alert",
                json=payload,
            )
            if resp.status_code >= 400:
                logger.debug(f"WsPusher: alert push returned {resp.status_code}")
        except Exception as exc:
            logger.debug(f"WsPusher: alert push failed — {exc}")

    async def push_summary(self, cycle: int, summary: Dict[str, Any]) -> None:
        """Push an end-of-cycle summary.

        Args:
            cycle: Cycle number.
            summary: Full cycle summary dict.
        """
        client = await self._get_client()
        if client is None:
            return

        payload: Dict[str, Any] = {
            "type": "cycle_summary",
            "cycle": cycle,
            "data": summary,
        }
        try:
            resp = await client.post(
                f"{self.api_url}/api/v2/pipeline/summary",
                json=payload,
            )
            if resp.status_code >= 400:
                logger.debug(f"WsPusher: summary push returned {resp.status_code}")
        except Exception as exc:
            logger.debug(f"WsPusher: summary push failed — {exc}")

    async def close(self) -> None:
        """Clean up the HTTP client."""
        if self._http is not None:
            await self._http.aclose()
            self._http = None
