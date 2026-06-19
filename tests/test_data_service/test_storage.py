"""tests/test_data_service/test_storage.py – Tests for ParquetStore and MetadataStore."""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from services.data_service.storage.parquet_store import ParquetStore


class TestParquetStore:
    """Tests for ParquetStore."""

    @pytest.fixture
    def temp_dir(self) -> str:
        with tempfile.TemporaryDirectory() as td:
            yield td

    @pytest.fixture
    def store(self, temp_dir: str) -> ParquetStore:
        return ParquetStore(data_dir=temp_dir)

    @pytest.fixture
    def sample_df(self) -> pd.DataFrame:
        dates = pd.date_range("2024-01-01", periods=50, freq="B")
        return pd.DataFrame({
            "open": np.random.randn(50).cumsum() + 100,
            "high": np.random.randn(50).cumsum() + 102,
            "low": np.random.randn(50).cumsum() + 98,
            "close": np.random.randn(50).cumsum() + 100,
            "adj_close": np.random.randn(50).cumsum() + 100,
            "volume": np.random.randint(1000000, 50000000, 50),
        }, index=dates)

    def test_write_and_read(self, store: ParquetStore, sample_df: pd.DataFrame):
        store.write_daily("TEST", sample_df)
        result = store.read_daily("TEST")
        assert result is not None
        assert len(result) == len(sample_df)
        assert "close" in result.columns

    def test_read_date_range(self, store: ParquetStore, sample_df: pd.DataFrame):
        store.write_daily("TEST", sample_df)
        result = store.read_daily("TEST", start=date(2024, 2, 1))
        assert result is not None
        assert len(result) < len(sample_df)

    def test_deduplication_on_append(self, store: ParquetStore, sample_df: pd.DataFrame):
        store.write_daily("TEST", sample_df)
        store.write_daily("TEST", sample_df)  # Append same data
        result = store.read_daily("TEST")
        assert len(result) == len(sample_df)  # Should be deduplicated

    def test_list_tickers(self, store: ParquetStore, sample_df: pd.DataFrame):
        store.write_daily("AAPL", sample_df)
        store.write_daily("MSFT", sample_df)
        tickers = store.list_tickers()
        assert "AAPL" in tickers
        assert "MSFT" in tickers

    def test_delete_ticker(self, store: ParquetStore, sample_df: pd.DataFrame):
        store.write_daily("TEST", sample_df)
        assert store.delete_ticker("TEST") is True
        assert store.read_daily("TEST") is None

    def test_write_minute_bars(self, store: ParquetStore, sample_df: pd.DataFrame):
        small_df = sample_df.head(390)  # ~1 day of minute bars
        store.write_minute("AAPL", date(2024, 1, 2), small_df)
        result = store.read_minute("AAPL", date(2024, 1, 2))
        assert result is not None

    def test_get_storage_stats(self, store: ParquetStore, sample_df: pd.DataFrame):
        store.write_daily("AAPL", sample_df)
        stats = store.get_storage_stats()
        assert stats["daily_files"] >= 1
        assert stats["daily_size_mb"] > 0
