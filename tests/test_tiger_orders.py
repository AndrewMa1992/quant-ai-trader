"""Tiger paper/demo orders must be real Order objects the app can see."""

from __future__ import annotations

import pytest

import shared.tiger_orders as to
from pathlib import Path


class _Contract:
    def __init__(self, symbol, currency):
        self.symbol = symbol
        self.currency = currency


class _Order:
    def __init__(self, **kwargs):
        self.account = kwargs.get("account")
        self.contract = kwargs.get("contract")
        self.action = kwargs.get("action")
        self.quantity = kwargs.get("quantity")
        self.limit_price = kwargs.get("limit_price")
        self.order_type = "LMT"
        self.time_in_force = None
        self.outside_rth = False
        self.trading_session_type = None
        self.user_mark = None
        self.id = None
        self.order_id = None
        self.status = None


def _stock_contract(*, symbol, currency):
    return _Contract(symbol, currency)


def _limit_order(**kwargs):
    return _Order(**kwargs)


def _market_order(**kwargs):
    order = _Order(**kwargs)
    order.order_type = "MKT"
    return order


@pytest.fixture
def order_tools(monkeypatch):
    monkeypatch.setattr(to, "_import_order_tools", lambda: (_stock_contract, _limit_order, _market_order))
    return True


def test_symbol_and_market_helpers():
    assert to.market_for_ticker("AAPL") == "US"
    assert to.symbol_for_ticker("AAPL") == "AAPL"
    assert to.market_for_ticker("0700.HK") == "HK"
    assert to.symbol_for_ticker("0700.HK") == "00700"
    assert to.currency_for_market("HK") == "HKD"


def test_align_tick_us():
    assert to.align_tick(256.653, "MRVL") == 256.65


def test_order_was_accepted():
    assert to.order_was_accepted({"order_id": "1", "status": "NEW"})
    assert not to.order_was_accepted({"order_id": "x", "status": "PAPER_SUBMITTED"})
    assert not to.order_was_accepted({"status": "FAILED", "error": "boom"})
    assert not to.order_was_accepted(None)


def test_paper_order_is_limit_outside_rth(order_tools):
    order = to.build_stock_order(
        account="21837535188693626",
        ticker="AAPL",
        side="BUY",
        quantity=2,
        order_type="MKT",
        limit_price=100.0,
        paper=True,
    )
    assert order.order_type == "LMT"
    assert order.outside_rth is True
    assert order.account == "21837535188693626"
    assert order.contract.symbol == "AAPL"
    assert order.limit_price > 100.0
    assert order.time_in_force == "DAY"


def test_submit_passes_order_object_not_kwargs(order_tools):
    captured: list = []

    class Trade:
        def place_order(self, order):
            captured.append(order)
            order.id = 43400000000000001
            order.status = "NEW"
            return order.id

    result = to.submit_stock_order(
        Trade(),
        account="21837535188693626",
        ticker="STX",
        side="SELL",
        quantity=1,
        order_type="MKT",
        limit_price=880.0,
        paper=True,
    )
    assert len(captured) == 1
    assert not isinstance(captured[0], dict)
    assert captured[0].action == "SELL"
    assert result["order_id"] == "43400000000000001"
    assert result["status"] == "NEW"
    assert result["outside_rth"] is True


def test_broker_source_does_not_pass_contract_none():
    src = Path("services/execution_service/live/tiger_broker.py").read_text(encoding="utf-8")
    assert "contract=None" not in src
    assert "submit_stock_order" in src
    data_src = Path("services/data_service/ingestion/tiger_client.py").read_text(encoding="utf-8")
    assert "contract=None" not in data_src


def test_us_24h_open_outside_regular_hours(monkeypatch):
    monkeypatch.setenv("QAT_US_24H_TRADING", "true")
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from shared.core.datetime_utils import MarketTimeHelper

    helper = MarketTimeHelper("US")
    wed_night = datetime(2026, 9, 2, 3, 30, tzinfo=ZoneInfo("America/New_York"))
    assert helper.is_market_open(wed_night) is True


def test_paper_executor_sends_limit_and_price():
    src = Path("shared/tiger_executor.py").read_text(encoding="utf-8")
    assert 'order_type="LMT"' in src
    assert "price=None" not in src.split("def _execute_paper")[1][:2500]
    assert "order_was_accepted" in src
