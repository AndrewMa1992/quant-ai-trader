"""Insert core CN A-share stocks into the ticker_info table.

One-time script: inserts core Shanghai 50 + Shenzhen Component Index
stocks into the ``ticker_info`` table with proper ``.SH`` / ``.SZ``
suffixes, so the China market data adapter can discover and fetch
A-share data.

Usage:
    python scripts/populate_cn_stocks.py
"""

from __future__ import annotations

import os
import sqlite3
import sys
import uuid
from datetime import datetime

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_PROJECT_ROOT)

# SSE 50 (Shanghai) + SZSE Component core (Shenzhen) constituents
CN_STOCKS: list[tuple[str, str, str, str]] = [
    # ── SSE 50 (Shanghai) ──
    ("600000.SH", "SPD Bank", "CN", "Banking"),
    ("600036.SH", "China Merchants Bank", "CN", "Banking"),
    ("600519.SH", "Kweichow Moutai", "CN", "Liquor"),
    ("600276.SH", "Hengrui Medicine", "CN", "Pharma"),
    ("600030.SH", "CITIC Securities", "CN", "Securities"),
    ("600887.SH", "Yili", "CN", "Food"),
    ("600406.SH", "NARI Technology", "CN", "Power"),
    ("600050.SH", "China Unicom", "CN", "Telecom"),
    ("601318.SH", "Ping An Insurance", "CN", "Insurance"),
    ("601166.SH", "Industrial Bank", "CN", "Banking"),
    ("601398.SH", "ICBC", "CN", "Banking"),
    ("601857.SH", "PetroChina", "CN", "Oil"),
    ("601288.SH", "Agricultural Bank of China", "CN", "Banking"),
    ("601988.SH", "Bank of China", "CN", "Banking"),
    ("601628.SH", "China Life Insurance", "CN", "Insurance"),
    # ── SZSE Component core (Shenzhen) ──
    ("000001.SZ", "Ping An Bank", "CN", "Banking"),
    ("000002.SZ", "China Vanke A", "CN", "Real Estate"),
    ("000063.SZ", "ZTE", "CN", "Telecom"),
    ("000333.SZ", "Midea Group", "CN", "Home Appliances"),
    ("000651.SZ", "Gree Electric", "CN", "Home Appliances"),
    ("000858.SZ", "Wuliangye", "CN", "Liquor"),
    ("002594.SZ", "BYD", "CN", "Auto"),
    ("002415.SZ", "Hikvision", "CN", "Security"),
    ("300750.SZ", "CATL", "CN", "Batteries"),
    ("300059.SZ", "East Money", "CN", "Securities"),
]


def main() -> None:
    """Insert CN A-share stocks into ticker_info table."""
    db_path = os.path.join(_PROJECT_ROOT, "data", "quant_trader.db")
    if not os.path.exists(db_path):
        print(f"ERROR: database not found at {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check table schema
    cursor.execute("PRAGMA table_info(ticker_info)")
    cols = [row[1] for row in cursor.fetchall()]
    print(f"ticker_info columns: {cols}")

    now = datetime.now().isoformat()
    added = 0
    skipped = 0

    for ticker, name, market, sector in CN_STOCKS:
        try:
            # Check if already exists
            cursor.execute("SELECT COUNT(*) FROM ticker_info WHERE ticker=?", (ticker,))
            if cursor.fetchone()[0] > 0:
                print(f"  {ticker} ({name}) already exists, skipping")
                skipped += 1
                continue

            # Insert with all available columns (include NOT NULL fields)
            stock_id = uuid.uuid4().hex  # 32-char hex, matching existing format
            cursor.execute(
                """INSERT INTO ticker_info
                   (ticker, name, market, sector, industry, currency, exchange,
                    is_active, is_etf, market_cap, shares_outstanding,
                    id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'CNY', ?, 1, 0, 0, 0, ?, ?, ?)""",
                (ticker, name, market, sector, sector,
                 "SSE" if ticker.endswith(".SH") else "SZSE",
                 stock_id, now, now),
            )
            added += 1
            print(f"  Added {ticker} ({name}) — {market} {sector}")
        except Exception as e:
            print(f"  Error adding {ticker}: {e}")

    conn.commit()
    print(f"\nDone: {added} added, {skipped} skipped")

    # Verify
    cursor.execute(
        "SELECT COUNT(*) FROM ticker_info WHERE ticker LIKE '%.SH' OR ticker LIKE '%.SZ'"
    )
    cn_count = cursor.fetchone()[0]
    print(f"Total CN stocks in ticker_info: {cn_count}")

    conn.close()


if __name__ == "__main__":
    main()
