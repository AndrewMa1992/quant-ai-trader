"""tests/conftest.py – Shared pytest fixtures for Quant AI Trader v2.

Provides:
- Async database session fixture (with transaction rollback)
- FastAPI TestClient fixture
- Redis mock fixture
- Sample data fixtures
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator, Generator
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from configs.settings import settings
from shared.models.base import Base


# ── Test Database ────────────────────────────────────────────
@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create a session-scoped event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def test_engine():
    """Create an in-memory SQLite async engine for tests."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        future=True,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncIterator[AsyncSession]:
    """Provide an async database session with automatic rollback."""
    session_factory = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        async with session.begin():
            yield session
            await session.rollback()


# ── FastAPI Test Client ──────────────────────────────────────
@pytest.fixture
def test_client() -> TestClient:
    """Create a FastAPI TestClient for the API gateway."""
    from api_gateway.main import app
    return TestClient(app)


@pytest.fixture
def test_client_with_auth(test_client: TestClient) -> TestClient:
    """Create a TestClient with the API key pre-configured."""
    test_client.headers["X-API-Key"] = settings.API_KEY
    return test_client


# ── Redis Mock ───────────────────────────────────────────────
@pytest.fixture
def mock_redis() -> Generator[MagicMock, None, None]:
    """Mock the Redis client for unit tests."""
    with patch("shared.redis_client.RedisClient", autospec=True) as mock:
        client = mock.return_value
        client.connect = AsyncMock()
        client.disconnect = AsyncMock()
        client.ping = AsyncMock(return_value=True)
        client.cache_get = AsyncMock(return_value=None)
        client.cache_get_json = AsyncMock(return_value=None)
        client.cache_set = AsyncMock(return_value=True)
        client.cache_delete = AsyncMock(return_value=1)
        client.cache_exists = AsyncMock(return_value=False)
        client.publish = AsyncMock(return_value=1)
        client.stream_add = AsyncMock(return_value="1-0")
        client.stream_read = AsyncMock(return_value=[])
        client.is_connected = True
        yield client


# ── Sample Data Fixtures ─────────────────────────────────────
@pytest.fixture
def sample_tickers() -> list[dict[str, Any]]:
    """Sample ticker data for tests."""
    return [
        {"ticker": "AAPL", "name": "Apple Inc.", "market": "US", "sector": "Technology", "currency": "USD"},
        {"ticker": "0700.HK", "name": "Tencent Holdings", "market": "HK", "sector": "Technology", "currency": "HKD"},
        {"ticker": "D05.SI", "name": "DBS Group", "market": "SG", "sector": "Financials", "currency": "SGD"},
    ]


@pytest.fixture
def sample_factors() -> list[dict[str, Any]]:
    """Sample factor definitions for tests."""
    return [
        {"id": "F001", "name": "ret_1m", "category": "technical", "direction": 1},
        {"id": "F100", "name": "pe_ratio", "category": "fundamental", "direction": -1},
        {"id": "F300", "name": "bid_ask_spread", "category": "microstructure", "direction": -1},
    ]


@pytest.fixture
def sample_daily_bars() -> list[dict[str, Any]]:
    """Sample daily OHLCV bars for testing."""
    return [
        {
            "ticker": "AAPL",
            "trade_date": "2024-01-02",
            "open": 185.00,
            "high": 187.50,
            "low": 184.20,
            "close": 186.80,
            "volume": 52000000,
        },
        {
            "ticker": "AAPL",
            "trade_date": "2024-01-03",
            "open": 187.00,
            "high": 189.00,
            "low": 186.50,
            "close": 188.50,
            "volume": 48000000,
        },
    ]


@pytest.fixture
def sample_signals() -> list[dict[str, Any]]:
    """Sample trading signals for tests."""
    return [
        {
            "ticker": "AAPL",
            "signal_date": "2024-01-03",
            "direction": 1,
            "strength": 0.85,
            "target_weight": 0.05,
            "predicted_return": 0.012,
            "confidence": 0.78,
        },
        {
            "ticker": "MSFT",
            "signal_date": "2024-01-03",
            "direction": -1,
            "strength": 0.62,
            "target_weight": -0.03,
            "predicted_return": -0.008,
            "confidence": 0.65,
        },
    ]


# ── Environment Setup / Teardown ─────────────────────────────
@pytest.fixture(autouse=True)
def setup_test_env() -> Generator[None, None, None]:
    """Automatically set test environment variables for all tests."""
    os.environ["QAT_ENV"] = "test"
    os.environ["QAT_DEBUG"] = "true"
    os.environ["QAT_POSTGRES_ECHO_SQL"] = "false"
    yield


# ── Helpers ──────────────────────────────────────────────────
@pytest.fixture
def anyio_backend() -> str:
    """Specify the async backend for anyio-based tests."""
    return "asyncio"
