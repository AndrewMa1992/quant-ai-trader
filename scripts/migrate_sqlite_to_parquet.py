"""Export SQLite daily_bars table data into ParquetStore format.

One-time migration script: reads all daily bar data from the SQLite
``daily_bars`` table and writes one Parquet file per ticker into the
ParquetStore ``cache/market_data/daily/`` directory.

Usage:
    python scripts/migrate_sqlite_to_parquet.py
"""

from __future__ import annotations

import os
import sqlite3
import sys

import pandas as pd

# Ensure project root is on the path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_PROJECT_ROOT)
sys.path.insert(0, _PROJECT_ROOT)

from services.data_service.storage.parquet_store import ParquetStore


def main() -> None:
    """Run the SQLite → Parquet migration."""
    db_path = os.path.join(_PROJECT_ROOT, "data", "quant_trader.db")
    if not os.path.exists(db_path):
        print(f"ERROR: database not found at {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Read table structure
    cursor.execute("PRAGMA table_info(daily_bars)")
    all_cols = [row[1] for row in cursor.fetchall()]
    print(f"daily_bars columns: {all_cols}")

    # Columns to keep (OHLCV + adjustment data), drop metadata
    drop_cols = {"id", "created_at", "updated_at", "ticker"}
    keep_cols = [c for c in all_cols if c not in drop_cols]

    # Get all distinct tickers
    cursor.execute("SELECT DISTINCT ticker FROM daily_bars")
    tickers = [row[0] for row in cursor.fetchall()]
    print(f"Tickers to migrate: {len(tickers)}")

    store = ParquetStore()
    migrated = 0
    skipped = 0

    for ticker in tickers:
        cursor.execute(
            "SELECT * FROM daily_bars WHERE ticker=? ORDER BY trade_date",
            (ticker,),
        )
        rows = cursor.fetchall()
        if not rows:
            skipped += 1
            continue

        # Build DataFrame with all columns
        df = pd.DataFrame(rows, columns=all_cols)

        # Drop metadata columns
        df = df[keep_cols].copy()

        # Convert trade_date to datetime and set as index
        if "trade_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["trade_date"])
            df = df.set_index("trade_date")
            df.index.name = "date"
        elif "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
            df.index.name = "date"

        # Ensure numeric columns are float
        numeric_cols = ["open", "high", "low", "close", "adj_close",
                        "volume", "turnover", "vwap", "splits_factor",
                        "dividends_amount"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Sort by date
        df = df.sort_index()

        # Strip timezone info for consistency (existing parquet may be tz-aware)
        if hasattr(df.index, "tz") and df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        # Delete existing parquet file for clean migration (avoids tz mismatch
        # on concat with previously-written tz-aware data)
        store.delete_ticker(ticker)

        # Write to ParquetStore
        store.write_daily(ticker, df)
        migrated += 1
        print(f"  Migrated {ticker}: {len(df)} bars")

    print(f"\nMigration complete: {migrated} tickers migrated, {skipped} skipped")
    conn.close()


if __name__ == "__main__":
    main()
