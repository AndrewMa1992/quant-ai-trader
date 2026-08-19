"""Tests for capital-aware paper trading policy."""

from shared.capital_policy import build_capital_policy
from shared.market_session import get_market_status, is_market_open, next_open_markets


def test_micro_account_policy_for_1700():
    pol = build_capital_policy(1700.0)
    assert pol.min_trade_value < 100
    assert pol.max_position_frac >= 0.30
    assert pol.deploy_frac >= 0.80
    assert pol.max_daily_trades >= 20


def test_us_24h_open():
    assert is_market_open("US") is True
    status = get_market_status()
    assert status["US"] is True
    assert "HK" in status and "SG" in status


def test_next_open_includes_us():
    opened = next_open_markets(["US", "HK", "SG", "AU", "NZ"])
    assert "US" in opened


def test_risk_manager_uses_capital_policy():
    from shared.risk_manager import RiskManager

    rm = RiskManager(initial_capital=1700.0, max_daily_trades=0)
    assert rm.MIN_TRADE_VALUE < 100
    assert rm.MAX_POSITION_SIZE >= 0.30
    assert rm.max_daily_trades >= 20
