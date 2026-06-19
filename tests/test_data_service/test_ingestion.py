"""tests/test_data_service/test_ingestion.py – Tests for data ingestion clients."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from services.data_service.ingestion.yfinance_client import YFinanceClient
from services.data_service.ingestion.eodhd_client import EODHDClient
from services.data_service.ingestion.fred_client import FREDClient
from shared.core.exceptions import DataFetchError


class TestYFinanceClient:
    """Tests for YFinanceClient."""

    @pytest.fixture
    def client(self) -> YFinanceClient:
        return YFinanceClient()

    @pytest.fixture
    def sample_df(self) -> pd.DataFrame:
        dates = pd.date_range("2024-01-01", periods=100, freq="B")
        return pd.DataFrame({
            "Open": range(100, 200),
            "High": range(101, 201),
            "Low": range(99, 199),
            "Close": range(100, 200),
            "Adj Close": range(100, 200),
            "Volume": [1000000] * 100,
        }, index=dates)

    @pytest.mark.asyncio
    async def test_fetch_daily_columns_standardized(self, client: YFinanceClient, sample_df: pd.DataFrame):
        """Test that column names are lowercased."""
        with patch.object(client, "_fetch_sync", return_value=sample_df):
            result = await client.fetch_daily("AAPL", date(2024, 1, 1), date(2024, 5, 1))
            assert result is not None
            assert all(c.islower() for c in result.columns)

    @pytest.mark.asyncio
    async def test_fetch_daily_rate_limit(self, client: YFinanceClient, sample_df: pd.DataFrame):
        """Test rate limiting is enforced."""
        import time
        with patch.object(client, "_fetch_sync", return_value=sample_df):
            t0 = time.monotonic()
            await client.fetch_daily("AAPL")
            t1 = time.monotonic()
            await client.fetch_daily("MSFT")
            t2 = time.monotonic()
            # Second call should be delayed
            assert (t2 - t1) >= 1.8  # ~2 seconds

    @pytest.mark.asyncio
    async def test_fetch_daily_retry_on_failure(self, client: YFinanceClient):
        """Test retry behavior on failure."""
        with patch.object(client, "_fetch_sync", side_effect=[
            ConnectionError("timeout"),
            ConnectionError("timeout"),
            pd.DataFrame({"Open": [100], "Close": [100]}),
        ]):
            result = await client.fetch_daily("AAPL")
            assert result is not None


class TestEODHDClient:
    """Tests for EODHDClient."""

    def test_not_available_without_api_key(self):
        client = EODHDClient(api_key="")
        assert not client.is_available

    @pytest.mark.asyncio
    async def test_returns_none_when_not_configured(self):
        client = EODHDClient(api_key="")
        result = await client.fetch_daily("AAPL.US")
        assert result is None


class TestFREDClient:
    """Tests for FREDClient."""

    def test_not_available_without_api_key(self):
        client = FREDClient(api_key="")
        assert not client.is_available

    @pytest.mark.asyncio
    async def test_returns_none_when_not_configured(self):
        client = FREDClient(api_key="")
        result = await client.fetch_series("DGS10")
        assert result is None
