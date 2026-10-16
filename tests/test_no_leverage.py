"""Cash-only trading: buying power is never a license to buy."""

from unittest.mock import MagicMock

import numpy as np

from shared.no_leverage import account_is_levered, cap_buy_quantity, spendable_cash


def test_negative_cash_buys_nothing():
    assert cap_buy_quantity(1502, 133.74, -304986.84) == 0
    assert spendable_cash(-304986.84) == 0


def test_positive_cash_stays_inside_budget():
    qty = cap_buy_quantity(10_000, 100.0, 1_000.0, usage=0.95)
    assert qty * 100.0 <= 1_000.0 * 0.95
    assert qty == 9.5


def test_negative_cash_is_leverage_even_without_a_leverage_field():
    assert account_is_levered({"cash": -304986.84, "buying_power": 2_281_692.63}) is True
    assert account_is_levered({"cash": 1_000.0, "buying_power": 2_000.0, "leverage": 1.0}) is False
    assert account_is_levered({"leverage": 1.0}) is False
    assert account_is_levered(None) is False


def test_check_leverage_blocks_negative_cash():
    from shared.risk_manager import RiskManager

    rm = RiskManager()
    assert rm.check_leverage({"cash": -1000.0, "leverage": 1.0}) is True
    assert rm.check_leverage({"cash": 500.0, "leverage": 1.0}) is False


def test_sync_keeps_negative_cash_instead_of_buying_power():
    from shared.portfolio_manager import PortfolioManager

    pf = PortfolioManager(initial_capital=1_000_000.0)
    pf.cash = 2_281_692.63
    tiger = MagicMock()
    tiger.is_connected.return_value = True
    tiger.connect.return_value = True
    tiger.get_positions.return_value = [
        {"ticker": "ORCL", "shares": 100, "avg_cost": 130.0, "market_value": 13000.0},
    ]
    tiger.get_account_info.return_value = {
        "cash": -304986.84,
        "buying_power": 2281692.63,
        "nav": 1010984.26,
        "total_value": 1010984.26,
        "net_liquidation": 1010984.26,
    }

    result = pf.sync_from_tiger(tiger, force=True)
    assert result["synced"] is True
    assert pf.cash == -304986.84
    assert result["cash"] == -304986.84


def test_rebalance_does_not_buy_on_negative_cash_or_open_shorts():
    from shared.portfolio_manager import PortfolioManager
    from shared.risk_manager import RiskManager
    from shared.tiger_executor import TigerExecutor

    pf = PortfolioManager(initial_capital=1_000_000.0)
    pf.cash = -304986.84
    pf.total_value = 1_010_984.26
    pf.positions["ORCL"] = 100.0
    pf.positions["CVX"] = -10.0
    rm = RiskManager(initial_capital=1_000_000.0)
    rm.sync_portfolio_value(1_010_984.26, -304986.84)
    rm.daily_start_value = 1_010_984.26
    tiger = MagicMock()
    tiger.is_connected.return_value = False
    tiger.get_account_info.return_value = {"cash": -304986.84, "buying_power": 2281692.63}

    executor = TigerExecutor(mode="paper", portfolio=pf, risk=rm, tiger_bridge=tiger)
    orders = executor.execute_rebalance(
        {"ORCL": 0.01, "AAPL": 0.20, "CVX": 0.0},
        {"ORCL": 130.0, "AAPL": 180.0, "CVX": 150.0},
        block_buys=True,
    )
    assert tiger.place_order.called is False
    assert all(o.get("side") != "buy" for o in orders)
    assert pf.positions.get("CVX", 0) < 0 or "CVX" not in [o.get("ticker") for o in orders if o.get("side") == "sell"]


def test_paper_buy_returns_none_when_broker_cash_is_negative():
    from shared.portfolio_manager import PortfolioManager
    from shared.risk_manager import RiskManager
    from shared.tiger_executor import TigerExecutor

    pf = PortfolioManager(initial_capital=1_000_000.0)
    pf.cash = 50_000.0
    pf.total_value = 1_010_984.26
    rm = RiskManager(initial_capital=1_000_000.0)
    rm.sync_portfolio_value(1_010_984.26, 50_000.0)
    rm.daily_start_value = 1_010_984.26
    tiger = MagicMock()
    tiger.get_account_info.return_value = {"cash": -304986.84, "buying_power": 2281692.63}
    executor = TigerExecutor(mode="paper", portfolio=pf, risk=rm, tiger_bridge=tiger)
    trade = executor._execute_paper("AAPL", "BUY", 10, 180.0, "test")
    assert trade is None
    assert tiger.place_order.called is False
    assert pf.cash == 50_000.0


def test_drawdown_peak_index_when_history_is_shorter_than_the_window():
    """The old dates[-(days - max_idx)] raises when len(dates) < days."""
    dates = ["2026-10-15", "2026-10-16"]
    drawdowns = [0.0, 0.02]
    days = 365
    window = np.asarray(drawdowns, dtype=float)[-days:]
    max_idx = int(np.argmax(np.where(np.isfinite(window), window, -np.inf)))
    idx = len(dates) - len(window) + max_idx
    assert dates[idx] == "2026-10-16"
    try:
        dates[-(days - max_idx)]
        raised = False
    except IndexError:
        raised = True
    assert raised is True


def test_factor_routes_do_not_synthesize_series():
    from pathlib import Path

    src = Path("services/factor_service/api/routes.py").read_text(encoding="utf-8")
    assert "np.random" not in src
    assert "synthetic" not in src.lower()
