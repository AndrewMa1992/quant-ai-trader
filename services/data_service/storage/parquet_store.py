"""services/data_service/storage/parquet_store.py – Parquet-based market data storage.

Organized as: {data_dir}/daily/{ticker}.parquet
Append-mode with deduplication. Uses zstd compression.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Union

import pandas as pd
from loguru import logger

from services.data_service.config import data_config


class ParquetStore:
    """Columnar storage for market data using Parquet files.

    Each ticker gets one Parquet file in the daily/ directory.
    Minute data stored in minute/YYYY-MM/ directory.

    Attributes:
        data_dir: Root directory for data storage.
        compression: Parquet compression codec.
    """

    def __init__(self, data_dir: str | None = None) -> None:
        self.data_dir = Path(data_dir or data_config.DATA_DIR)
        self.compression = data_config.PARQUET_COMPRESSION
        self._daily_dir = self.data_dir / "daily"
        self._minute_dir = self.data_dir / "minute"
        self._daily_dir.mkdir(parents=True, exist_ok=True)
        self._minute_dir.mkdir(parents=True, exist_ok=True)

    def _ticker_path(self, ticker: str) -> Path:
        """Get the Parquet file path for a ticker.

        Args:
            ticker: Stock ticker symbol.

        Returns:
            Path to the Parquet file.
        """
        safe_ticker = ticker.replace("/", "_").replace("\\", "_")
        return self._daily_dir / f"{safe_ticker}.parquet"

    def _minute_path(self, ticker: str, bar_date: date) -> Path:
        """Get the minute bar Parquet path.

        Args:
            ticker: Stock ticker.
            bar_date: Date of the bars.

        Returns:
            Path to the minute bar Parquet file.
        """
        safe_ticker = ticker.replace("/", "_").replace("\\", "_")
        month_dir = self._minute_dir / bar_date.strftime("%Y-%m")
        month_dir.mkdir(parents=True, exist_ok=True)
        return month_dir / f"{safe_ticker}_{bar_date.isoformat()}.parquet"

    def write_daily(self, ticker: str, df: pd.DataFrame) -> None:
        """Write or append daily OHLCV data to Parquet.

        Deduplicates by date index before writing.

        Args:
            ticker: Stock ticker symbol.
            df: DataFrame with DatetimeIndex and OHLCV columns.
        """
        if df is None or df.empty:
            logger.warning(f"Empty DataFrame for {ticker}, skipping write")
            return

        df = df.copy()
        # Standardize column names
        df.columns = [c.lower().replace(" ", "_") for c in df.columns]

        # ── Ensure date index ────────────────────────────────────────
        date_col: Optional[str] = None

        if isinstance(df.index, pd.DatetimeIndex):
            pass  # Already good
        else:
            # Search for a date column (case-insensitive, common variants)
            date_candidates = [
                "date", "datetime", "timestamp", "time", "index",
                "trade_date", "bar_date",
            ]
            # Also check capitalized variants from raw data
            for col in df.columns:
                if col.lower() in date_candidates:
                    date_col = col
                    break
            # Fallback: try uppercase first-letter variants
            if date_col is None:
                for candidate in ["Date", "DateTime", "Timestamp"]:
                    if candidate in df.columns:
                        date_col = candidate
                        break

            if date_col is not None:
                try:
                    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
                    df = df.dropna(subset=[date_col])
                    df = df.set_index(date_col)
                except Exception as e:
                    logger.error(f"Failed to parse date column '{date_col}' for {ticker}: {e}")
                    return
            elif isinstance(df.index, pd.Index) and df.index.dtype.kind in ("i", "f"):
                # Integer/float index — use as-is but warn
                logger.warning(
                    f"No date column/index for {ticker} — using integer index as row key. "
                    f"Columns: {list(df.columns)[:6]}"
                )
            else:
                # Last resort: try to reset and find ANY date-like column
                found = False
                for col in df.columns:
                    try:
                        converted = pd.to_datetime(df[col], errors="coerce")
                        if converted.notna().sum() > len(df) * 0.7:
                            df[col] = converted
                            df = df.dropna(subset=[col])
                            df = df.set_index(col)
                            found = True
                            logger.debug(f"Auto-detected date column '{col}' for {ticker}")
                            break
                    except Exception:
                        continue
                if not found:
                    logger.error(
                        f"No date index for {ticker} — cannot write to Parquet. "
                        f"Columns: {list(df.columns)[:8]}"
                    )
                    return

        path = self._ticker_path(ticker)

        if path.exists():
            # Read existing, combine, deduplicate
            existing = pd.read_parquet(path)
            if not existing.empty:
                df = pd.concat([existing, df])
                df = df[~df.index.duplicated(keep="last")]
                df = df.sort_index()

        df.to_parquet(path, compression=self.compression, index=True)
        logger.debug(f"Wrote {len(df)} bars for {ticker} → {path}")

    def read_daily(
        self,
        ticker: str,
        start: date | None = None,
        end: date | None = None,
    ) -> Optional[pd.DataFrame]:
        """Read daily OHLCV data from Parquet.

        Args:
            ticker: Stock ticker symbol.
            start: Start date filter.
            end: End date filter.

        Returns:
            DataFrame with OHLCV data, or None if not found.
        """
        path = self._ticker_path(ticker)
        if not path.exists():
            return None

        df = pd.read_parquet(path)

        if df.empty:
            return None

        # Ensure DatetimeIndex for date-based filtering
        if not isinstance(df.index, pd.DatetimeIndex):
            # Try to convert from common date column names
            date_candidates = ["date", "datetime", "timestamp", "trade_date"]
            date_col = None
            for col in date_candidates:
                if col in df.columns:
                    date_col = col
                    break
            # Also try auto-detection
            if date_col is None:
                for col in df.columns:
                    try:
                        converted = pd.to_datetime(df[col], errors="coerce")
                        if converted.notna().sum() > len(df) * 0.7:
                            date_col = col
                            break
                    except Exception:
                        continue

            if date_col is not None:
                df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
                df = df.dropna(subset=[date_col])
                df = df.set_index(date_col)
            # If still not a DatetimeIndex, return as-is (caller handles)

        # Strip timezone from index for consistent naive-timestamp comparisons
        if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        # Filter by date range (only if we have a DatetimeIndex)
        if isinstance(df.index, pd.DatetimeIndex):
            if start:
                df = df[df.index >= pd.Timestamp(start)]
            if end:
                df = df[df.index <= pd.Timestamp(end)]

        return df.sort_index()

    def write_minute(self, ticker: str, bar_date: date, df: pd.DataFrame) -> None:
        """Write minute bar data to Parquet.

        Args:
            ticker: Stock ticker.
            bar_date: Date of the bars.
            df: DataFrame with datetime index and OHLCV columns.
        """
        if df is None or df.empty:
            return

        path = self._minute_path(ticker, bar_date)
        df.to_parquet(path, compression=self.compression, index=True)
        logger.debug(f"Wrote minute bars for {ticker} → {path}")

    def read_minute(
        self,
        ticker: str,
        bar_date: date,
    ) -> Optional[pd.DataFrame]:
        """Read minute bar data from Parquet.

        Args:
            ticker: Stock ticker.
            bar_date: Date to read.

        Returns:
            DataFrame or None.
        """
        path = self._minute_path(ticker, bar_date)
        if not path.exists():
            return None

        df = pd.read_parquet(path)
        return df if not df.empty else None

    def list_tickers(self) -> list[str]:
        """List all tickers with stored data.

        Returns:
            List of ticker symbols.
        """
        tickers = []
        for f in self._daily_dir.glob("*.parquet"):
            tickers.append(f.stem)
        return sorted(tickers)

    def delete_ticker(self, ticker: str) -> bool:
        """Delete all stored data for a ticker.

        Args:
            ticker: Stock ticker.

        Returns:
            True if deleted, False if not found.
        """
        path = self._ticker_path(ticker)
        if path.exists():
            path.unlink()
            logger.info(f"Deleted {ticker} data")
            return True
        return False

    def get_date_range(self, ticker: str) -> tuple[date, date] | None:
        """Get the available date range for a ticker.

        Args:
            ticker: Stock ticker.

        Returns:
            (start_date, end_date) tuple or None.
        """
        df = self.read_daily(ticker)
        if df is None or df.empty:
            return None

        start = df.index.min()
        end = df.index.max()
        return (start.date() if hasattr(start, "date") else start,
                end.date() if hasattr(end, "date") else end)

    def get_storage_stats(self) -> dict:
        """Get storage statistics.

        Returns:
            Dictionary with directory sizes and file counts.
        """
        daily_size = sum(
            f.stat().st_size for f in self._daily_dir.glob("*.parquet")
        )
        daily_count = len(list(self._daily_dir.glob("*.parquet")))

        minute_size = 0
        minute_count = 0
        for f in self._minute_dir.rglob("*.parquet"):
            minute_size += f.stat().st_size
            minute_count += 1

        return {
            "daily_files": daily_count,
            "daily_size_mb": round(daily_size / (1024 * 1024), 2),
            "minute_files": minute_count,
            "minute_size_mb": round(minute_size / (1024 * 1024), 2),
            "total_size_mb": round((daily_size + minute_size) / (1024 * 1024), 2),
        }
