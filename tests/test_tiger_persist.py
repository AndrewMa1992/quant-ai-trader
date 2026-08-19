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
