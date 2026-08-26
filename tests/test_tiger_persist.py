"""Unit tests for Tiger → SQLite persistence helpers."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture()
def tiger_db(tmp_path, monkeypatch):
    db = tmp_path / "quant_trader.db"
    import shared.tiger_persist as tp

    monkeypatch.setattr(tp, "DB_PATH", db)
    return tp


def test_normalize_position_quantity_alias(tiger_db):
    p = tiger_db.normalize_position({
        "symbol": "AAPL",
        "quantity": 10,
        "average_cost": 100,
        "market_price": 110,
    })
    assert p["ticker"] == "AAPL"
    assert p["shares"] == 10
    assert p["market_value"] == 1100


def test_persist_and_load_snapshot(tiger_db):
    snap = tiger_db.persist_tiger_snapshot(
        positions=[{
            "ticker": "MSFT",
            "shares": 5,
            "avg_cost": 300,
            "market_price": 320,
        }],
        account={"nav": 2000, "cash": 400},
        orders=[{
            "order_id": "oid-1",
            "ticker": "MSFT",
            "side": "BUY",
            "quantity": 5,
            "status": "FILLED",
            "avg_fill_price": 300,
        }],
    )
    assert snap["positions_synced"] == 1
    assert snap["nav"] == 2000
    assert snap["buying_power"] == 400
    assert any(o["order_id"] == "oid-1" for o in snap["orders"])

    api = tiger_db.load_positions_for_api()
    assert len(api["positions"]) == 1
    assert api["positions"][0]["ticker"] == "MSFT"
    assert api["summary"]["cash"] == 400

    orders = tiger_db.load_orders_for_api(limit=10)
    assert any(o["order_id"] == "oid-1" for o in orders)


def test_persist_fill(tiger_db):
    out = tiger_db.persist_fill("NVDA", "BUY", 2, 500.0, strategy="paper")
    assert out["ticker"] == "NVDA"
    orders = tiger_db.load_orders_for_api(limit=5, ticker="NVDA")
    assert len(orders) >= 1
    assert orders[0]["status"] == "FILLED"


def test_persist_snapshot_uuid_pk_schema(tiger_db):
    """Production SQLite uses SQLAlchemy UUID string PKs, not INTEGER AUTOINCREMENT."""
    conn = tiger_db._connect()
    try:
        conn.executescript(
            """
            DROP TABLE IF EXISTS portfolios;
            DROP TABLE IF EXISTS positions;
            DROP TABLE IF EXISTS orders;
            CREATE TABLE portfolios (
                id VARCHAR(32) NOT NULL PRIMARY KEY,
                snapshot_date DATE UNIQUE,
                nav REAL, gross_exposure REAL, net_exposure REAL,
                long_exposure REAL, short_exposure REAL, cash REAL,
                daily_pnl REAL DEFAULT 0, daily_return REAL DEFAULT 0,
                cumulative_return REAL DEFAULT 0,
                num_positions INTEGER DEFAULT 0, leverage REAL DEFAULT 1,
                created_at TEXT, updated_at TEXT
            );
            CREATE TABLE positions (
                id VARCHAR(32) NOT NULL PRIMARY KEY,
                ticker TEXT, position_date DATE, market TEXT,
                quantity INTEGER, avg_cost REAL, market_price REAL,
                market_value REAL, unrealized_pnl REAL DEFAULT 0,
                realized_pnl REAL DEFAULT 0, weight REAL DEFAULT 0,
                currency TEXT DEFAULT 'USD', fx_rate REAL DEFAULT 1,
                created_at TEXT, updated_at TEXT
            );
            CREATE TABLE orders (
                id VARCHAR(32) NOT NULL PRIMARY KEY,
                order_id TEXT UNIQUE, ticker TEXT, side TEXT, order_type TEXT,
                quantity INTEGER, filled_quantity INTEGER DEFAULT 0,
                avg_fill_price REAL, status TEXT, market TEXT,
                is_paper INTEGER DEFAULT 1, submitted_at TEXT,
                created_at TEXT, updated_at TEXT
            );
            """
        )
        conn.commit()
    finally:
        conn.close()

    snap = tiger_db.persist_tiger_snapshot(
        positions=[{"ticker": "AAPL", "shares": 2, "avg_cost": 100, "market_price": 110}],
        account={"nav": 1700, "cash": 1480},
        orders=[{"order_id": "t-1", "ticker": "AAPL", "side": "BUY", "quantity": 2, "status": "FILLED"}],
    )
    assert snap.get("error") is None
    assert snap["nav"] == 1700
    assert snap["positions_synced"] == 1
    api = tiger_db.load_positions_for_api()
    assert api["summary"]["cash"] == 1480
    assert api["positions"][0]["ticker"] == "AAPL"

