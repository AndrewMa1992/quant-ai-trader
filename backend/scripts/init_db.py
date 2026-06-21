#!/usr/bin/env python3
"""backend/scripts/init_db.py — DB initialization and Parquet-to-SQLite import.

Operations:
  1. Ensure all v2 SQLAlchemy tables exist (via check/repair)
  2. Import data/daily/*.parquet files into daily_bars table
  3. Update ticker_info metadata based on available data
  4. Verify data integrity after import

Usage:
    python -m backend.scripts.init_db              # Full init: verify schema + import parquet
    python -m backend.scripts.init_db --dry-run    # Report what would be imported
    python -m backend.scripts.init_db --verify     # Verify only, no import
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from loguru import logger

# ── Path resolution ────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DB_PATH = _PROJECT_ROOT / "data" / "quant_trader.db"
_PARQUET_DIR = _PROJECT_ROOT / "data" / "daily"


def get_db_path() -> Path:
    """Resolve DB path from config, falling back to default."""
    try:
        sys.path.insert(0, str(_PROJECT_ROOT))
        from configs.settings import settings
        return settings.DB_PATH
    except ImportError:
        return _DB_PATH


def get_parquet_dir() -> Path:
    """Get the daily parquet data directory."""
    return _PARQUET_DIR


# ═══════════════════════════════════════════════════════════════════
# Schema Verification
# ═══════════════════════════════════════════════════════════════════

REQUIRED_TABLES: Dict[str, str] = {
    "daily_bars": """
        CREATE TABLE IF NOT EXISTS daily_bars (
            id TEXT PRIMARY KEY,
            ticker VARCHAR(20) NOT NULL,
            trade_date DATE NOT NULL,
            open FLOAT NOT NULL,
            high FLOAT NOT NULL,
            low FLOAT NOT NULL,
            close FLOAT NOT NULL,
            adj_close FLOAT,
            volume BIGINT NOT NULL,
            turnover FLOAT,
            vwap FLOAT,
            splits_factor FLOAT DEFAULT 1.0,
            dividends_amount FLOAT DEFAULT 0.0,
            created_at DATETIME DEFAULT (datetime('now')),
            updated_at DATETIME DEFAULT (datetime('now')),
            UNIQUE(ticker, trade_date)
        )
    """,
    "signals": """
        CREATE TABLE IF NOT EXISTS signals (
            id TEXT PRIMARY KEY,
            ticker VARCHAR(20) NOT NULL,
            signal_date DATE NOT NULL,
            horizon VARCHAR(10) NOT NULL,
            direction INTEGER NOT NULL,
            strength FLOAT NOT NULL,
            target_weight FLOAT NOT NULL,
            predicted_return FLOAT NOT NULL,
            confidence FLOAT NOT NULL,
            risk_score FLOAT,
            is_executed BOOLEAN DEFAULT 0,
            created_at DATETIME DEFAULT (datetime('now')),
            updated_at DATETIME DEFAULT (datetime('now')),
            UNIQUE(ticker, signal_date, horizon)
        )
    """,
    "trades": """
        CREATE TABLE IF NOT EXISTS trades (
            id TEXT PRIMARY KEY,
            ticker VARCHAR(20) NOT NULL,
            trade_date DATE NOT NULL,
            trade_time DATETIME NOT NULL,
            side VARCHAR(10) NOT NULL,
            quantity INTEGER NOT NULL,
            price FLOAT NOT NULL,
            commission FLOAT DEFAULT 0.0,
            slippage_bps FLOAT DEFAULT 0.0,
            notional FLOAT NOT NULL,
            order_id VARCHAR(64),
            execution_id VARCHAR(64),
            signal_id VARCHAR(64),
            market VARCHAR(10) NOT NULL,
            currency VARCHAR(10) DEFAULT 'USD',
            strategy VARCHAR(50),
            notes TEXT,
            created_at DATETIME DEFAULT (datetime('now')),
            updated_at DATETIME DEFAULT (datetime('now'))
        )
    """,
}


def ensure_schema(db_path: Path) -> bool:
    """Ensure all required tables exist in the database.

    Args:
        db_path: Path to SQLite database.

    Returns:
        True if all tables exist or were created successfully.
    """
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    cursor = conn.cursor()

    existing = {
        row[0]
        for row in cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    logger.info(f"Found {len(existing)} existing tables in {db_path}")

    created: List[str] = []
    for table_name, ddl in REQUIRED_TABLES.items():
        if table_name in existing:
            logger.debug(f"  ✅ {table_name} — exists")
        else:
            cursor.execute(ddl)
            conn.commit()
            created.append(table_name)
            logger.info(f"  📦 {table_name} — created")

    # Ensure indexes
    _ensure_indexes(cursor)

    conn.commit()
    conn.close()

    if created:
        logger.info(f"Created {len(created)} new tables: {created}")
    logger.info("Schema verification complete — all required tables present")
    return True


def _ensure_indexes(cursor: sqlite3.Cursor) -> None:
    """Create recommended indexes if they don't exist."""
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_daily_bars_ticker ON daily_bars(ticker)",
        "CREATE INDEX IF NOT EXISTS idx_daily_bars_date ON daily_bars(trade_date)",
        "CREATE INDEX IF NOT EXISTS idx_signals_ticker ON signals(ticker)",
        "CREATE INDEX IF NOT EXISTS idx_signals_date ON signals(signal_date)",
        "CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker)",
        "CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(trade_date)",
    ]
    for idx_sql in indexes:
        cursor.execute(idx_sql)


# ═══════════════════════════════════════════════════════════════════
# Parquet → daily_bars Import
# ═══════════════════════════════════════════════════════════════════

def _determine_market(ticker: str) -> str:
    """Determine market from ticker suffix."""
    if ".HK" in ticker:
        return "HK"
    if ".SI" in ticker:
        return "SG"
    if ".AX" in ticker:
        return "AU"
    if ".NZ" in ticker:
        return "NZ"
    return "US"


def import_parquet_to_db(
    db_path: Path,
    parquet_dir: Path,
    dry_run: bool = False,
    batch_size: int = 1000,
) -> Dict[str, int]:
    """Import all Parquet files from data/daily/ into daily_bars table.

    Args:
        db_path: Path to SQLite database.
        parquet_dir: Directory containing *.parquet files.
        dry_run: If True, only report what would be done.
        batch_size: Rows per INSERT batch.

    Returns:
        Dict with keys: files_processed, bars_imported, errors.
    """
    parquet_files = sorted(parquet_dir.glob("*.parquet"))
    if not parquet_files:
        logger.warning(f"No Parquet files found in {parquet_dir}")
        return {"files_processed": 0, "bars_imported": 0, "errors": 0}

    logger.info(f"Found {len(parquet_files)} Parquet files in {parquet_dir}")

    results: Dict[str, int] = {"files_processed": 0, "bars_imported": 0, "errors": 0}
    total_bars: int = 0

    for pf in parquet_files:
        ticker: str = pf.stem  # Filename without extension = ticker
        try:
            df = pd.read_parquet(pf)
            if df.empty:
                logger.debug(f"  ⏭ {ticker}: empty file, skipping")
                continue

            results["files_processed"] += 1

            if dry_run:
                logger.info(
                    f"  [DRY-RUN] {ticker}: {len(df)} rows, "
                    f"{df.index[0]} → {df.index[-1]}"
                )
                total_bars += len(df)
                continue

            # Normalize columns
            df = df.copy()
            df.columns = [c.lower().replace(" ", "_") for c in df.columns]

            # Ensure Date index
            if not isinstance(df.index, pd.DatetimeIndex):
                if "date" in df.columns:
                    df["date"] = pd.to_datetime(df["date"])
                    df = df.set_index("date")
                else:
                    logger.warning(f"  ⚠ {ticker}: no date index, skipping")
                    results["errors"] += 1
                    continue

            bars_written: int = _upsert_daily_bars(
                db_path, ticker, df, batch_size
            )
            total_bars += bars_written
            results["bars_imported"] += bars_written

            logger.info(
                f"  ✅ {ticker}: {bars_written} bars "
                f"({df.index[0].strftime('%Y-%m-%d') if hasattr(df.index[0], 'strftime') else str(df.index[0])} → "
                f"{df.index[-1].strftime('%Y-%m-%d') if hasattr(df.index[-1], 'strftime') else str(df.index[-1])})"
            )

        except Exception as exc:
            logger.error(f"  ❌ {ticker}: {exc}")
            results["errors"] += 1

    if dry_run:
        logger.info(
            f"\n[DRY-RUN] Would import {total_bars:,} bars "
            f"from {results['files_processed']} files"
        )
    else:
        logger.info(
            f"\n✅ Import complete: {results['bars_imported']:,} bars "
            f"from {results['files_processed']} files "
            f"({results['errors']} errors)"
        )

    return results


def _upsert_daily_bars(
    db_path: Path,
    ticker: str,
    df: pd.DataFrame,
    batch_size: int = 1000,
) -> int:
    """Upsert daily bars into the daily_bars table.

    Uses INSERT OR REPLACE with the UNIQUE(ticker, trade_date) constraint.

    Args:
        db_path: Database path.
        ticker: Ticker symbol.
        df: DataFrame with DatetimeIndex and OHLCV columns.
        batch_size: Rows per batch.

    Returns:
        Number of rows written.
    """
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA cache_size=-64000")
    cursor = conn.cursor()

    written: int = 0
    batch: List[tuple] = []

    for idx, row in df.iterrows():
        trade_date: str = (
            idx.strftime("%Y-%m-%d")
            if hasattr(idx, "strftime")
            else str(idx)[:10]
        )

        record = (
            str(uuid.uuid4()),                          # id
            ticker,                                      # ticker
            trade_date,                                  # trade_date
            float(row.get("open", 0.0)),                # open
            float(row.get("high", 0.0)),                # high
            float(row.get("low", 0.0)),                 # low
            float(row.get("close", 0.0)),               # close
            float(row.get("adj_close", row.get("close", 0.0))),  # adj_close
            int(row.get("volume", 0)),                   # volume
            float(row.get("turnover", 0.0)) if "turnover" in row else None,  # turnover
            float(row.get("vwap", 0.0)) if "vwap" in row else None,          # vwap
            1.0,                                         # splits_factor
            0.0,                                         # dividends_amount
            datetime.now().isoformat(),                  # created_at
            datetime.now().isoformat(),                  # updated_at
        )
        batch.append(record)

        if len(batch) >= batch_size:
            cursor.executemany(
                """INSERT OR REPLACE INTO daily_bars
                   (id, ticker, trade_date, open, high, low, close, adj_close,
                    volume, turnover, vwap, splits_factor, dividends_amount,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                batch,
            )
            conn.commit()
            written += len(batch)
            batch.clear()

    # Flush remaining batch
    if batch:
        cursor.executemany(
            """INSERT OR REPLACE INTO daily_bars
               (id, ticker, trade_date, open, high, low, close, adj_close,
                volume, turnover, vwap, splits_factor, dividends_amount,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            batch,
        )
        conn.commit()
        written += len(batch)

    conn.close()
    return written


# ═══════════════════════════════════════════════════════════════════
# ticker_info Metadata Sync
# ═══════════════════════════════════════════════════════════════════

def sync_ticker_metadata(db_path: Path) -> int:
    """Synchronize ticker_info metadata with available parquet data.

    Ensures all tickers with daily_bars have entries in ticker_info.
    Uses data from backend.config for known tickers, falls back to
    creating minimal entries for unknown ones.

    Returns:
        Number of new ticker_info records inserted.
    """
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Get all tickers with daily_bars
    cursor.execute("SELECT DISTINCT ticker FROM daily_bars ORDER BY ticker")
    bar_tickers = {row[0] for row in cursor.fetchall()}

    # Get existing ticker_info tickers
    cursor.execute("SELECT ticker FROM ticker_info")
    existing_tickers = {row[0] for row in cursor.fetchall()}

    missing = bar_tickers - existing_tickers
    if not missing:
        logger.info("ticker_info metadata is up to date")
        conn.close()
        return 0

    inserted: int = 0
    for ticker in sorted(missing):
        market: str = _determine_market(ticker)
        search_name: str = ticker.split(".")[0] if "." in ticker else ticker
        cursor.execute(
            """INSERT INTO ticker_info
               (id, ticker, name, market, sector, currency, is_active, is_etf,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, '', ?, 1, 0, datetime('now'), datetime('now'))""",
            (str(uuid.uuid4()), ticker, search_name, market, _currency_for_market(market)),
        )
        inserted += 1

    conn.commit()
    conn.close()
    logger.info(f"Added {inserted} new ticker_info records")
    return inserted


def _currency_for_market(market: str) -> str:
    """Return default currency for a market code."""
    return {"US": "USD", "HK": "HKD", "SG": "SGD", "AU": "AUD", "NZ": "NZD"}.get(market, "USD")


# ═══════════════════════════════════════════════════════════════════
# Data Integrity Check
# ═══════════════════════════════════════════════════════════════════

def verify_integrity(db_path: Path) -> Dict[str, any]:
    """Run data integrity checks after import.

    Returns:
        Dict with check results.
    """
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    result: Dict[str, any] = {
        "daily_bars": {},
        "signals": {},
        "trades": {},
        "ticker_info": {},
        "overall_ok": True,
    }

    # daily_bars: row count, ticker count, date range
    cursor.execute("SELECT COUNT(*) FROM daily_bars")
    result["daily_bars"]["row_count"] = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT ticker) FROM daily_bars")
    result["daily_bars"]["ticker_count"] = cursor.fetchone()[0]

    cursor.execute(
        "SELECT MIN(trade_date), MAX(trade_date) FROM daily_bars"
    )
    min_d, max_d = cursor.fetchone()
    result["daily_bars"]["date_range"] = f"{min_d} → {max_d}" if min_d else "N/A"

    # Null checks on critical columns
    cursor.execute(
        "SELECT COUNT(*) FROM daily_bars WHERE close IS NULL OR open IS NULL"
    )
    null_bars = cursor.fetchone()[0]
    result["daily_bars"]["null_critical"] = null_bars
    if null_bars > 0:
        result["overall_ok"] = False

    # signals
    cursor.execute("SELECT COUNT(*) FROM signals")
    result["signals"]["row_count"] = cursor.fetchone()[0]

    # trades
    cursor.execute("SELECT COUNT(*) FROM trades")
    result["trades"]["row_count"] = cursor.fetchone()[0]

    # ticker_info
    cursor.execute("SELECT COUNT(*) FROM ticker_info")
    result["ticker_info"]["row_count"] = cursor.fetchone()[0]

    conn.close()
    return result


# ═══════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Initialize DB: ensure schema + import Parquet data",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be imported without making changes",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Only verify data integrity, skip import",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Override database path",
    )
    parser.add_argument(
        "--parquet-dir",
        type=str,
        default=None,
        help="Override parquet data directory",
    )
    parser.add_argument(
        "--skip-import",
        action="store_true",
        help="Skip parquet import, only ensure schema and metadata",
    )
    args = parser.parse_args()

    db_path = Path(args.db_path) if args.db_path else get_db_path()
    parquet_dir = (
        Path(args.parquet_dir) if args.parquet_dir else get_parquet_dir()
    )

    logger.info(f"DB path:   {db_path}")
    logger.info(f"Parquet:   {parquet_dir}")

    if not db_path.exists():
        logger.error(f"Database not found at {db_path}")
        sys.exit(1)

    # Step 1: Ensure schema
    logger.info("=" * 60)
    logger.info("Step 1: Verifying database schema...")
    ensure_schema(db_path)

    # Step 2: Import parquet data
    if not args.skip_import and not args.verify:
        logger.info("=" * 60)
        logger.info("Step 2: Importing Parquet data → daily_bars...")
        import_results = import_parquet_to_db(
            db_path, parquet_dir, dry_run=args.dry_run
        )
        logger.info(
            f"Import results: {import_results['bars_imported']:,} bars, "
            f"{import_results['errors']} errors"
        )

    # Step 3: Sync ticker metadata
    if not args.verify:
        logger.info("=" * 60)
        logger.info("Step 3: Synchronizing ticker_info metadata...")
        new_tickers = sync_ticker_metadata(db_path)
        logger.info(f"  {new_tickers} new ticker_info entries added")

    # Step 4: Verify integrity
    logger.info("=" * 60)
    logger.info("Step 4: Data integrity check...")
    integrity = verify_integrity(db_path)
    logger.info(f"  daily_bars: {integrity['daily_bars']['row_count']:,} rows, "
                f"{integrity['daily_bars']['ticker_count']} tickers, "
                f"range {integrity['daily_bars']['date_range']}")
    logger.info(f"  signals:    {integrity['signals']['row_count']:,} rows")
    logger.info(f"  trades:     {integrity['trades']['row_count']:,} rows")
    logger.info(f"  ticker_info: {integrity['ticker_info']['row_count']} rows")

    if integrity["overall_ok"]:
        logger.info("✅ All integrity checks passed")
    else:
        logger.warning(
            f"⚠️  Integrity issues found: "
            f"{integrity['daily_bars'].get('null_critical', 0)} null critical values"
        )

    logger.info("=" * 60)
    logger.info("Init DB complete!")


if __name__ == "__main__":
    main()
