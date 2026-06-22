"""添加 CN A 股核心股票到 ticker_info 表。

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

# 上证50 (Shanghai) + 深证成指核心 (Shenzhen) 成分股
CN_STOCKS: list[tuple[str, str, str, str]] = [
    # ── 上证50 (Shanghai) ──
    ("600000.SH", "浦发银行", "CN", "银行"),
    ("600036.SH", "招商银行", "CN", "银行"),
    ("600519.SH", "贵州茅台", "CN", "白酒"),
    ("600276.SH", "恒瑞医药", "CN", "医药"),
    ("600030.SH", "中信证券", "CN", "证券"),
    ("600887.SH", "伊利股份", "CN", "食品"),
    ("600406.SH", "国电南瑞", "CN", "电力"),
    ("600050.SH", "中国联通", "CN", "通信"),
    ("601318.SH", "中国平安", "CN", "保险"),
    ("601166.SH", "兴业银行", "CN", "银行"),
    ("601398.SH", "工商银行", "CN", "银行"),
    ("601857.SH", "中国石油", "CN", "石油"),
    ("601288.SH", "农业银行", "CN", "银行"),
    ("601988.SH", "中国银行", "CN", "银行"),
    ("601628.SH", "中国人寿", "CN", "保险"),
    # ── 深证成指核心 (Shenzhen) ──
    ("000001.SZ", "平安银行", "CN", "银行"),
    ("000002.SZ", "万科A", "CN", "地产"),
    ("000063.SZ", "中兴通讯", "CN", "通信"),
    ("000333.SZ", "美的集团", "CN", "家电"),
    ("000651.SZ", "格力电器", "CN", "家电"),
    ("000858.SZ", "五粮液", "CN", "白酒"),
    ("002594.SZ", "比亚迪", "CN", "汽车"),
    ("002415.SZ", "海康威视", "CN", "安防"),
    ("300750.SZ", "宁德时代", "CN", "电池"),
    ("300059.SZ", "东方财富", "CN", "证券"),
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
