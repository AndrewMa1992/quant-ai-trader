"""
WsPusher — push cycle / tiger snapshots to API gateway WS bridge.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx
from loguru import logger


def default_gateway_url() -> str:
    """Gateway the execution service and pipeline should push live snapshots to.

    Inside Docker this is http://api-gateway:8001 (QAT_GATEWAY_URL). On a single
    host it follows QAT_API_PORT, default 8001.
    """
    explicit = os.getenv("QAT_GATEWAY_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    port = os.getenv("QAT_API_PORT", "8001").strip() or "8001"
    return f"http://127.0.0.1:{port}"


class WsPusher:
    """Non-blocking dashboard pusher via gateway REST→WS bridge."""

    def __init__(
        self,
        api_url: str = "",
        enabled: bool = True,
        timeout: float = 3.0,
    ) -> None:
        self.api_url: str = api_url.rstrip("/") if api_url else default_gateway_url()
        self.enabled: bool = enabled
        self.timeout: float = timeout
        self._http: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> Optional[httpx.AsyncClient]:
        if not self.enabled:
            return None
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout))
        return self._http

    async def _post(self, path: str, payload: Dict[str, Any]) -> None:
        client = await self._get_client()
        if client is None:
            return
        try:
            resp = await client.post(f"{self.api_url}{path}", json=payload)
            if resp.status_code >= 400:
                logger.debug(f"WsPusher {path} → {resp.status_code}")
        except Exception as exc:
            logger.debug(f"WsPusher {path} failed — {exc}")

    async def push_step_update(self, cycle: int, step: int, data: Dict[str, Any]) -> None:
        await self._post(
            "/api/v2/push/cycle-data",
            {"type": "step_update", "cycle": cycle, "step": step, "data": data},
        )

    async def push_alert(self, alert_type: str, message: str) -> None:
        await self._post(
            "/api/v2/push/cycle-data",
            {"type": "alert", "alert_type": alert_type, "message": message},
        )

    async def push_summary(self, cycle: int, summary: Dict[str, Any]) -> None:
        await self._post(
            "/api/v2/push/cycle-data",
            {"type": "cycle_summary", "cycle": cycle, "data": summary},
        )

    async def push_tiger_snapshot(self, snapshot: Dict[str, Any]) -> None:
        await self._post("/api/v2/push/tiger-snapshot", snapshot)

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None
