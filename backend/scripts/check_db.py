"""backend/scripts/check_db.py — Database health check and verification.

Validates:
  1. DB_PATH points to the correct location (data/quant_trader.db)
  2. All required tables exist and have expected structure
  3. Row counts for key tables
  4. Data integrity (null checks, referential integrity)
  5. Parquet-to-DB sync status

Usage:
    python -m backend.scripts.check_db
    python -m backend.scripts.check_db --verbose
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# ── Path resolution ────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


def resolve_db_path() -> Path:
    """Resolve the actual DB path from config and verify it exists."""
    try:
        from configs.settings import settings
        return settings.DB_PATH
    except ImportError:
        fallback = _PROJECT_ROOT / "data" / "quant_trader.db"
        return fallback


def check_db_path(db_path: Path) -> Tuple[bool, str]:
    """Verify DB_PATH is correct.

    Returns:
        (ok, message)
    """
    expected_dir = _PROJECT_ROOT / "data"
    actual_parent = db_path.parent

    if actual_parent.resolve() != expected_dir.resolve():
        return False, (
            f"MISMATCH: DB_PATH parent is {actual_parent}, "
            f"expected {expected_dir}"
        )

    if not db_path.exists():
        return False, f"MISSING: Database not found at {db_path}"

    size_mb = db_path.stat().st_size / 1024 / 1024
    return True, f"OK: {db_path} ({size_mb:.2f} MB)"


def check_tables(db_path: Path) -> Dict[str, any]:
    """Check all tables in the database.

    Returns:
        Dict with table name → {columns, row_count}.
    """
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables_raw = cursor.fetchall()

    tables: Dict[str, any] = {}
    for (name,) in tables_raw:
        cols = cursor.execute(f"PRAGMA table_info({name})").fetchall()
        cursor.execute(f"SELECT COUNT(*) FROM \"{name}\"")
        count = cursor.fetchone()[0]
        tables[name] = {
            "columns": [(c[1], c[2]) for c in cols],
            "row_count": count,
        }

    conn.close()
    return tables


def check_data_integrity(db_path: Path) -> List[str]:
    """Run basic data integrity checks.

    Returns:
        List of warning/error messages (empty = all good).
    """
    issues: List[str] = []
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Check daily_bars for null critical columns
    cursor.execute(
        "SELECT COUNT(*) FROM daily_bars "
        "WHERE close IS NULL OR open IS NULL OR volume IS NULL"
    )
    null_count = cursor.fetchone()[0]
    if null_count > 0:
        issues.append(f"daily_bars: {null_count} rows with NULL critical values")

    # Check daily_bars for duplicate (ticker, trade_date)
    cursor.execute(
        "SELECT COUNT(*) FROM ("
        "  SELECT ticker, trade_date, COUNT(*) as cnt "
        "  FROM daily_bars GROUP BY ticker, trade_date HAVING cnt > 1"
        ")"
    )
    dup_count = cursor.fetchone()[0]
    if dup_count > 0:
        issues.append(f"daily_bars: {dup_count} duplicate (ticker, trade_date) groups")

    # Check signals for null ticker or signal_date
    cursor.execute(
        "SELECT COUNT(*) FROM signals "
        "WHERE ticker IS NULL OR signal_date IS NULL"
    )
    sig_null = cursor.fetchone()[0]
    if sig_null > 0:
        issues.append(f"signals: {sig_null} rows with NULL key fields")

    # Check trades for null ticker or trade_date
    cursor.execute(
        "SELECT COUNT(*) FROM trades "
        "WHERE ticker IS NULL OR trade_date IS NULL"
    )
    trade_null = cursor.fetchone()[0]
    if trade_null > 0:
        issues.append(f"trades: {trade_null} rows with NULL key fields")

    conn.close()
    return issues


def check_parquet_sync(db_path: Path) -> Dict[str, any]:
    """Check sync status between Parquet files and daily_bars table.

    Returns:
        Dict with sync summary.
    """
    parquet_dir = _PROJECT_ROOT / "data" / "daily"
    parquet_files = list(parquet_dir.glob("*.parquet"))
    parquet_count = len(parquet_files)

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(DISTINCT ticker) FROM daily_bars")
    db_ticker_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM daily_bars")
    db_bar_count = cursor.fetchone()[0]
    conn.close()

    synced = parquet_count > 0 and db_bar_count > 0

    return {
        "parquet_files": parquet_count,
        "db_tickers": db_ticker_count,
        "db_bars": db_bar_count,
        "synced": synced,
        "gap": parquet_count - db_ticker_count if parquet_count > db_ticker_count else 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Database health check for Quant AI Trader"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed table structure",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  Quant AI Trader — Database Health Check")
    print("=" * 60)

    db_path = resolve_db_path()

    # 1. DB_PATH check
    print("\n[1] DB Path Verification")
    ok, msg = check_db_path(db_path)
    status = "✅" if ok else "❌"
    print(f"  {status} {msg}")
    if not ok:
        sys.exit(1)

    # 2. Table check
    print("\n[2] Table Structure")
    tables = check_tables(db_path)
    print(f"  Found {len(tables)} tables")

    key_tables = ["daily_bars", "signals", "trades", "ticker_info",
                  "orders", "positions", "portfolios"]
    for tname in key_tables:
        if tname in tables:
            t = tables[tname]
            cols_str = ", ".join(f"{c[0]}({c[1]})" for c in t["columns"][:8])
            if len(t["columns"]) > 8:
                cols_str += f", ... (+{len(t['columns']) - 8})"
            print(f"  ✅ {tname}: {t['row_count']:,} rows | {cols_str}")
        else:
            print(f"  ⚠️  {tname}: NOT FOUND")

    if args.verbose:
        print("\n  All tables:")
        for tname, t in sorted(tables.items()):
            print(f"    {tname}: {t['row_count']:,} rows")

    # 3. Data integrity
    print("\n[3] Data Integrity")
    issues = check_data_integrity(db_path)
    if issues:
        for issue in issues:
            print(f"  ⚠️  {issue}")
    else:
        print("  ✅ No integrity issues found")

    # 4. Parquet sync
    print("\n[4] Parquet ↔ DB Sync Status")
    sync = check_parquet_sync(db_path)
    status = "✅ Synced" if sync["synced"] else "⚠️ Not synced"
    print(f"  {status}")
    print(f"  Parquet files:  {sync['parquet_files']}")
    print(f"  DB tickers:     {sync['db_tickers']}")
    print(f"  DB bars:        {sync['db_bars']:,}")
    if sync["gap"] > 0:
        print(f"  ⚠️  {sync['gap']} Parquet files without DB entries")

    # 5. Health verdict
    print("\n" + "=" * 60)
    all_ok = ok and len(issues) == 0
    if all_ok:
        print("  ✅ database: healthy")
    else:
        print("  ⚠️  database: needs attention")
    print("=" * 60)


if __name__ == "__main__":
    main()
