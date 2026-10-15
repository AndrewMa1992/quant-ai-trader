"""Redis fallback TTL/retry and the Docker gateway URL used for live pushes."""

from __future__ import annotations

import asyncio
import time

from shared.redis_client import RedisClient
from shared.ws_pusher import default_gateway_url


class _FakeRedis:
    def __init__(self) -> None:
        self.calls = 0

    async def ping(self) -> bool:
        self.calls += 1
        if self.calls == 1:
            raise ConnectionError("down")
        return True


def _memory_client() -> RedisClient:
    client = RedisClient()
    client.client = None  # type: ignore[assignment]
    client._connected = False
    client._degraded = True
    return client


def test_memory_cache_expires() -> None:
    client = _memory_client()
    asyncio.run(client.cache_set("quote", "AAPL", ttl=30))
    assert asyncio.run(client.cache_get("quote")) == "AAPL"
    client._memory_cache["quote"] = ("AAPL", time.time() - 1)
    assert asyncio.run(client.cache_get("quote")) is None
    assert asyncio.run(client.cache_ttl("quote")) == -2


def test_ping_retries_after_a_failed_connect() -> None:
    client = _memory_client()
    fake = _FakeRedis()
    client.client = fake  # type: ignore[assignment]
    client._degraded = False
    client._last_attempt = 0.0

    assert asyncio.run(client.ping()) is False
    assert client.is_degraded

    client._last_attempt = 0.0
    assert asyncio.run(client.ping()) is True
    assert client.is_connected
    assert client.mode == "healthy"


def test_gateway_url_uses_docker_service_name(monkeypatch) -> None:
    monkeypatch.setenv("QAT_GATEWAY_URL", "http://api-gateway:8001/")
    assert default_gateway_url() == "http://api-gateway:8001"


def test_gateway_url_defaults_to_local_api_port(monkeypatch) -> None:
    monkeypatch.delenv("QAT_GATEWAY_URL", raising=False)
    monkeypatch.setenv("QAT_API_PORT", "8001")
    assert default_gateway_url() == "http://127.0.0.1:8001"
