"""Tests for Tiger asset/order parsers (no SDK, no FastAPI)."""
from __future__ import annotations

from types import SimpleNamespace

from shared.tiger_assets import merge_orders, parse_account_summary, parse_order, parse_position


def test_parse_summary_only():
    raw = SimpleNamespace(
        account="21837535188693626",
        summary=SimpleNamespace(cash=1700.5, net_liquidation=1700.5, buying_power=1700.5, currency="USD"),
        segments=None,
    )
    out = parse_account_summary(raw, account="21837535188693626")
    assert out["cash"] == 1700.5
    assert out["nav"] == 1700.5
    assert out["total_value"] == 1700.5
    assert out["buying_power"] == 1700.5


def test_parse_empty_summary_uses_segments_list():
    raw = SimpleNamespace(
        account="21837535188693626",
        summary=SimpleNamespace(cash=0, net_liquidation=0, buying_power=0),
        segments=[
            SimpleNamespace(capability="SEC", cash=1200.0, net_liquidation=1500.0, buying_power=1200.0, currency="USD"),
            SimpleNamespace(capability="FUT", cash=300.0, net_liquidation=300.0, buying_power=300.0, currency="USD"),
        ],
    )
    out = parse_account_summary(raw)
    assert out["cash"] == 1500.0
    assert out["nav"] == 1800.0
    assert out["buying_power"] == 1500.0
    assert len(out["segments"]) == 2


def test_parse_empty_summary_uses_segments_dict():
    raw = SimpleNamespace(
        account="21837535188693626",
        summary=SimpleNamespace(cash=0, net_liquidation=0, buying_power=float("inf")),
        segments={
            "SEC": SimpleNamespace(cash=800.0, net_liquidation=800.0, buying_power=800.0, currency="USD"),
        },
    )
    out = parse_account_summary(raw)
    assert out["cash"] == 800.0
    assert out["nav"] == 800.0
    assert out["buying_power"] == 800.0  # inf ignored, then segment/cash fallback


def test_parse_assets_list_picks_matching_account():
    live = SimpleNamespace(
        account="20874631",
        summary=SimpleNamespace(cash=0, net_liquidation=0, buying_power=0),
        segments=[],
    )
    paper = SimpleNamespace(
        account="21837535188693626",
        summary=SimpleNamespace(cash=99, net_liquidation=101, buying_power=99),
        segments=[],
    )
    out = parse_account_summary([live, paper], account="21837535188693626")
    assert out["account"] == "21837535188693626"
    assert out["cash"] == 99
    assert out["nav"] == 101


def test_parse_position_from_contract():
    pos = SimpleNamespace(
        contract=SimpleNamespace(symbol="AAPL"),
        quantity=10,
        average_cost=100,
        market_price=110,
        market_value=0,
        unrealized_pnl=100,
        currency="USD",
    )
    out = parse_position(pos)
    assert out["ticker"] == "AAPL"
    assert out["shares"] == 10
    assert out["market_value"] == 1100


def test_parse_order_and_merge():
    o1 = SimpleNamespace(
        id=111,
        contract=SimpleNamespace(symbol="MSFT"),
        action="BUY",
        quantity=5,
        filled=5,
        status="Filled",
        avg_fill_price=300,
    )
    o2 = SimpleNamespace(
        order_id=111,
        symbol="MSFT",
        side="BUY",
        quantity=5,
        status="Filled",
    )
    a = parse_order(o1)
    b = parse_order(o2)
    merged = merge_orders([a], [b])
    assert a["ticker"] == "MSFT"
    assert a["side"] == "BUY"
    assert len(merged) == 1
