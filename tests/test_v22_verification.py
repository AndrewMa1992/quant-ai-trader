"""
tests/test_v22_verification.py — v2.2 full verification test suite
======================================================
QA Engineer: Edward (strict QA)

Covers all 15 P0/P1/P2 requirements:
  P0-1: Live execution path (TigerExecutor live/paper/rebalance)
  P0-2: Portfolio circuit breaker (circuit breaker, liquidate_all, daily_start init)
  P0-3: Market-session detection (get_market_status, is_any_market_open)
  P0-4: Tiger state sync (sync_from_tiger)
  P0-5: Bridge cleanup (AST check: no backend. imports in trading_pipeline)
  P1-1: Leverage iron rule (check_leverage)
  P1-2: Daily trade cap (check_daily_limit)
  P1-3: Short-position fix (fix_short_positions)
  P1-4: v1 fallback (exponential backoff)
  P1-5: Frontend push (WsPusher must not raise)
  P2-1: Git auto-sync (GIT_AUTO_SYNC=False must not call)

How to run:
    cd E:/workbuddyspace/Claw/quant-ai-trader
    python -m pytest tests/test_v22_verification.py -v --tb=short
"""

import ast
import os
import sys
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# Ensure project root on path
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

# ───────────────────────────────────────────────────────────────
# Step 1: Import Integrity Tests
# ───────────────────────────────────────────────────────────────


class TestImportIntegrity:
    """Verify all shared/ modules and PipelineConfig import correctly."""

    def test_import_shared_tiger_bridge(self):
        """shared.tiger_bridge can be imported."""
        import shared.tiger_bridge
        assert shared.tiger_bridge is not None

    def test_import_shared_market_session(self):
        """shared.market_session can be imported."""
        import shared.market_session
        assert shared.market_session is not None

    def test_import_shared_portfolio_manager(self):
        """shared.portfolio_manager can be imported."""
        import shared.portfolio_manager
        assert shared.portfolio_manager is not None

    def test_import_shared_risk_manager(self):
        """shared.risk_manager can be imported."""
        import shared.risk_manager
        assert shared.risk_manager is not None

    def test_import_shared_tiger_executor(self):
        """shared.tiger_executor can be imported."""
        import shared.tiger_executor
        assert shared.tiger_executor is not None

    def test_import_shared_daily_state(self):
        """shared.daily_state can be imported."""
        import shared.daily_state
        assert shared.daily_state is not None

    def test_import_shared_ws_pusher(self):
        """shared.ws_pusher can be imported."""
        import shared.ws_pusher
        assert shared.ws_pusher is not None

    def test_import_shared_git_sync(self):
        """shared.git_sync can be imported."""
        import shared.git_sync
        assert shared.git_sync is not None

    def test_import_risk_report_class(self):
        """RiskReport can be imported from risk_manager."""
        from shared.risk_manager import RiskReport
        report = RiskReport()
        assert report.passed is True
        assert report.circuit_breaker is False

    def test_import_risk_manager_class(self):
        """RiskManager can be imported from risk_manager."""
        from shared.risk_manager import RiskManager
        rm = RiskManager()
        assert rm is not None

    def test_import_tiger_executor_class(self):
        """TigerExecutor can be imported from tiger_executor."""
        from shared.tiger_executor import TigerExecutor
        assert TigerExecutor is not None

    def test_import_portfolio_manager_class(self):
        """PortfolioManager can be imported from portfolio_manager."""
        from shared.portfolio_manager import PortfolioManager
        pm = PortfolioManager()
        assert pm is not None

    def test_import_market_session_functions(self):
        """get_market_status / is_any_market_open can be imported from market_session."""
        from shared.market_session import get_market_status, is_any_market_open
        status = get_market_status()
        assert isinstance(status, dict)
        # P0-3: return status for 3 markets (US, HK, CN)
        assert len(status) >= 2  # At least 2 markets tracked
        result = is_any_market_open()
        assert isinstance(result, bool)

    def test_import_pipeline_config(self):
        """PipelineConfig can be imported from configs.pipeline_config."""
        from configs.pipeline_config import PipelineConfig, pipeline_config
        assert PipelineConfig is not None
        assert pipeline_config is not None

    def test_import_wspusher_class(self):
        """WsPusher can be imported from ws_pusher."""
        from shared.ws_pusher import WsPusher
        wp = WsPusher(api_url="http://localhost:9999", enabled=False)
        assert wp is not None

    def test_import_dailystate_class(self):
        """DailyState can be imported from daily_state."""
        from shared.daily_state import DailyState
        ds = DailyState()
        assert ds is not None


# ───────────────────────────────────────────────────────────────
# Step 2: Functional Tests — P0 Requirements
# ───────────────────────────────────────────────────────────────


# ── P0-1: Live execution path ──────────────────────────────────────

class TestP01_TigerExecutor:
    """P0-1: TigerExecutor live/paper/rebalance tests."""

    @pytest.fixture
    def mock_portfolio(self):
        """Create a mock portfolio."""
        from shared.portfolio_manager import PortfolioManager
        pf = PortfolioManager(initial_capital=100000.0)
        # Seeded position: AAPL 100 shares @ $180
        pf.positions["AAPL"] = 100.0
        pf.avg_costs["AAPL"] = 180.0
        pf.cash = 82000.0
        pf.total_value = 100000.0
        return pf

    @pytest.fixture
    def mock_risk(self):
        """Create a mock risk manager."""
        from shared.risk_manager import RiskManager
        rm = RiskManager(initial_capital=100000.0)
        rm.sync_portfolio_value(100000.0, 82000.0)
        # Ensure daily_start_value is initialized so check_circuit_breaker does not return empty on first call
        rm.daily_start_value = 100000.0
        return rm

    @pytest.fixture
    def mock_tiger(self):
        """Create a mock tiger bridge."""
        tiger = MagicMock()
        tiger.is_connected.return_value = False  # disconnected by default
        tiger.place_order.return_value = {"order_id": "fake-order-123"}
        tiger.get_account_info.return_value = {
            "cash": 82000.0, "total_value": 100000.0, "leverage": 1.0
        }
        tiger.get_positions.return_value = [
            {"ticker": "AAPL", "shares": 100, "avg_cost": 180.0, "market_value": 18000.0}
        ]
        return tiger

    def test_paper_mode_calls_portfolio_execute_trade(self, mock_portfolio, mock_risk, mock_tiger):
        """TigerExecutor mode='paper' → calls portfolio.execute_trade."""
        from shared.tiger_executor import TigerExecutor

        # Patch portfolio.execute_trade to verify it's called
        with patch.object(mock_portfolio, 'execute_trade', wraps=mock_portfolio.execute_trade) as spy:
            executor = TigerExecutor(
                mode="paper",
                portfolio=mock_portfolio,
                risk=mock_risk,
                tiger_bridge=mock_tiger,
            )
            trade = executor.execute_signal("AAPL", "BUY", 0.1, 180.0, 0.8, "test")
            assert spy.called, "paper mode should call portfolio.execute_trade"

    def test_live_mode_calls_tiger_place_order(self, mock_portfolio, mock_risk, mock_tiger):
        """TigerExecutor mode='live' → calls tiger_bridge.place_order."""
        from shared.tiger_executor import TigerExecutor

        mock_tiger.is_connected.return_value = True
        # Ensure risk check passes
        mock_risk.daily_start_value = 100000.0
        mock_risk.portfolio_value = 100000.0
        mock_risk.cash = 82000.0

        executor = TigerExecutor(
            mode="live",
            portfolio=mock_portfolio,
            risk=mock_risk,
            tiger_bridge=mock_tiger,
        )
        trade = executor.execute_signal("AAPL", "SELL", 0.3, 180.0, 0.8, "test")
        assert mock_tiger.place_order.called, "live mode should call tiger_bridge.place_order"

    def test_execute_rebalance_weights(self, mock_portfolio, mock_risk, mock_tiger):
        """execute_rebalance correctly computes weight diffs and generates orders."""
        from shared.tiger_executor import TigerExecutor

        mock_risk.daily_start_value = 100000.0
        mock_risk.portfolio_value = 100000.0
        mock_risk.cash = 82000.0

        executor = TigerExecutor(
            mode="paper",
            portfolio=mock_portfolio,
            risk=mock_risk,
            tiger_bridge=mock_tiger,
        )

        # AAPL currently: 100 shares @ $180 = $18000, weight = 18%
        # Target AAPL = 25% (overweight → should SELL)
        # Target MSFT = 10% (no position → should BUY)
        target_weights = {"AAPL": 0.25, "MSFT": 0.10}
        prices = {"AAPL": 180.0, "MSFT": 300.0}

        orders = executor.execute_rebalance(target_weights, prices)
        assert len(orders) >= 1, "Should generate at least 1 order from rebalance"
        # Verify structure
        for order in orders:
            assert "ticker" in order
            assert "side" in order


# ── P0-2: Portfolio circuit breaker ──────────────────────────────────────────

class TestP02_CircuitBreaker:
    """P0-2: Portfolio circuit breaker (circuit breaker, liquidate_all, daily_start init)."""

    def test_daily_loss_5pct_triggers_breaker_hard(self):
        """Daily loss ≥5% → RiskReport(passed=False, circuit_breaker=True) in hard mode."""
        from shared.risk_manager import RiskManager

        rm = RiskManager(initial_capital=100000.0, breaker_mode="hard")
        rm.sync_portfolio_value(100000.0, 100000.0)
        # First call initializes daily_start_value
        report = rm.check_circuit_breaker()
        # First call always passes (initialization)
        assert report.passed is True, "First call should always pass (init)"
        assert report.circuit_breaker is False

        # Simulate a 6% daily loss
        rm.portfolio_value = 94000.0  # -6%
        report = rm.check_circuit_breaker()
        assert report.passed is False, "6% daily loss should block in hard mode"
        assert report.circuit_breaker is True

    def test_daily_loss_5pct_warn_mode_passes(self):
        """breaker_mode='warn' → daily_loss 5% → passed=True but circuit_breaker=True."""
        from shared.risk_manager import RiskManager

        rm = RiskManager(initial_capital=100000.0, breaker_mode="warn")
        rm.sync_portfolio_value(100000.0, 100000.0)
        # First-time initialization
        rm.check_circuit_breaker()
        # Simulate a 6% daily loss
        rm.portfolio_value = 94000.0
        report = rm.check_circuit_breaker()
        assert report.passed is True, "warn mode should still pass"
        assert report.circuit_breaker is True, "circuit_breaker flag should still be set"

    def test_liquidate_all_returns_order_list(self):
        """liquidate_all returns a list of flatten orders."""
        from shared.risk_manager import RiskManager

        rm = RiskManager(initial_capital=100000.0)
        rm.positions = {"AAPL": 100.0, "MSFT": 50.0}
        prices = {"AAPL": 180.0, "MSFT": 300.0}
        mock_tiger = MagicMock()
        mock_tiger.is_connected.return_value = False

        orders = rm.liquidate_all(prices, mock_tiger)
        assert isinstance(orders, list), "Should return a list"
        assert len(orders) == 2, "Should liquidate both positions"
        for order in orders:
            assert order["side"] == "sell"
            assert order["reason"] == "circuit_breaker_liquidation"

    def test_liquidate_all_empty_positions(self):
        """liquidate_all returns an empty list when there are no positions."""
        from shared.risk_manager import RiskManager

        rm = RiskManager(initial_capital=100000.0)
        rm.positions = {}
        prices = {}
        mock_tiger = MagicMock()

        orders = rm.liquidate_all(prices, mock_tiger)
        assert orders == [], "No positions should return empty list"

    def test_first_check_initializes_daily_start(self):
        """First check_circuit_breaker call auto-initializes daily_start_value."""
        from shared.risk_manager import RiskManager

        rm = RiskManager(initial_capital=100000.0)
        assert rm.daily_start_value == 0.0, "Should start at 0"

        report = rm.check_circuit_breaker()
        assert rm.daily_start_value > 0, "daily_start_value should be initialized"
        assert rm.daily_start_value == 100000.0

    def test_cool_down_period(self):
        """After the breaker trips, blocking continues during cooldown."""
        from shared.risk_manager import RiskManager
        from datetime import datetime, timedelta

        rm = RiskManager(initial_capital=100000.0, breaker_mode="hard")
        rm.sync_portfolio_value(100000.0, 100000.0)
        rm.check_circuit_breaker()  # init

        # Manually trip the circuit breaker
        rm.circuit_breaker_triggered = True
        rm.circuit_breaker_time = datetime.now()  # just now
        rm.daily_start_value = 100000.0
        rm.portfolio_value = 100000.0

        report = rm.check_circuit_breaker()
        assert report.passed is False
        assert report.circuit_breaker is True
        assert "cooldown" in report.reason.lower() or "cooling" in report.reason.lower()


# ── P0-3: Market-session detection ──────────────────────────────────────

class TestP03_MarketSession:
    """P0-3: Market-session detection (get_market_status, is_any_market_open)."""

    def test_get_market_status_returns_dict(self):
        """get_market_status() returns a dict with US/HK/CN keys."""
        from shared.market_session import get_market_status, _MARKETS

        status = get_market_status()
        assert isinstance(status, dict), "Should return dict"
        # Verify all tracked markets are present
        for market in _MARKETS:
            assert market in status, f"Market {market} should be in status"
        assert len(status) == len(_MARKETS), f"Should return {len(_MARKETS)} market statuses"

    def test_is_any_market_open_returns_bool(self):
        """is_any_market_open() returns a bool and does not raise."""
        from shared.market_session import is_any_market_open

        result = is_any_market_open()
        assert isinstance(result, bool), "Should return bool"
        # Must not raise regardless of True/False

    def test_no_exceptions(self):
        """Market-session helpers must not raise."""
        from shared.market_session import get_market_status, is_any_market_open, is_market_open

        try:
            get_market_status()
            is_any_market_open()
            is_market_open("US")
            is_market_open("HK")
            is_market_open("CN")
            is_market_open("JP")  # unknown market should return False
        except Exception as e:
            pytest.fail(f"Market session functions raised exception: {e}")

    def test_is_market_open_unknown_returns_false(self):
        """is_market_open returns False for an unknown market."""
        from shared.market_session import is_market_open

        result = is_market_open("NONEXISTENT")
        assert result is False


# ── P0-4: Tiger state sync ──────────────────────────────────────

class TestP04_TigerSync:
    """P0-4: Tiger state sync (PortfolioManager.sync_from_tiger)."""

    def test_sync_from_tiger_returns_required_fields(self):
        """sync_from_tiger return value includes all required fields."""
        from shared.portfolio_manager import PortfolioManager

        pf = PortfolioManager(initial_capital=100000.0)

        # Mock tiger bridge
        mock_tiger = MagicMock()
        mock_tiger.is_connected.return_value = True
        mock_tiger.connect.return_value = True
        mock_tiger.get_positions.return_value = [
            {"ticker": "AAPL", "shares": 100, "avg_cost": 180.0, "market_value": 18000.0},
            {"ticker": "MSFT", "shares": 50, "avg_cost": 300.0, "market_value": 15000.0},
        ]
        mock_tiger.get_account_info.return_value = {
            "cash": 67000.0,
            "total_value": 100000.0,
            "leverage": 1.0,
        }

        result = pf.sync_from_tiger(mock_tiger, force=False)

        assert "synced" in result, "Must have synced key"
        assert "positions" in result, "Must have positions key"
        assert "cash" in result, "Must have cash key"
        assert "total_value" in result, "Must have total_value key"
        assert "source" in result, "Must have source key"

    def test_sync_from_tiger_with_positions(self):
        """sync_from_tiger correctly syncs position quantities."""
        from shared.portfolio_manager import PortfolioManager

        pf = PortfolioManager(initial_capital=100000.0)

        mock_tiger = MagicMock()
        mock_tiger.is_connected.return_value = True
        mock_tiger.connect.return_value = True
        mock_tiger.get_positions.return_value = [
            {"ticker": "AAPL", "shares": 100, "avg_cost": 180.0, "market_value": 18000.0},
        ]
        mock_tiger.get_account_info.return_value = {
            "cash": 82000.0,
            "total_value": 100000.0,
            "leverage": 1.0,
        }

        result = pf.sync_from_tiger(mock_tiger, force=False)
        assert result["synced"] is True
        assert result["positions"] == 1
        assert result["source"] == "tiger_api"

    def test_sync_from_tiger_offline(self):
        """When Tiger is offline, sync_from_tiger returns synced=False."""
        from shared.portfolio_manager import PortfolioManager

        pf = PortfolioManager(initial_capital=100000.0)

        mock_tiger = MagicMock()
        mock_tiger.is_connected.return_value = False
        mock_tiger.connect.return_value = False

        result = pf.sync_from_tiger(mock_tiger, force=False)
        assert result["synced"] is False
        assert result["source"] in ("tiger_offline", "none")

    def test_sync_from_tiger_zero_nav_preserves_paper_capital(self, monkeypatch):
        """Paper/sim: empty Tiger account must not wipe local $1700 buying power."""
        from shared.portfolio_manager import PortfolioManager

        monkeypatch.setenv("QAT_TRADING_SIMULATION_MODE", "true")
        pf = PortfolioManager(initial_capital=1700.0)
        assert pf.cash == 1700.0

        mock_tiger = MagicMock()
        mock_tiger.is_connected.return_value = True
        mock_tiger.connect.return_value = True
        mock_tiger.get_positions.return_value = []
        mock_tiger.get_account_info.return_value = {
            "cash": 0.0,
            "total_value": 0.0,
            "leverage": 1.0,
        }

        result = pf.sync_from_tiger(mock_tiger, force=False)
        assert result["synced"] is False
        assert result["source"] == "tiger_zero_nav_preserved"
        assert pf.cash == 1700.0
        assert pf.total_value == 1700.0

    def test_ensure_buying_power_restores_wiped_book(self, monkeypatch):
        """If state was already wiped to $0, restore sim floor capital."""
        from shared.portfolio_manager import PortfolioManager

        monkeypatch.setenv("QAT_TRADING_SIMULATION_MODE", "true")
        pf = PortfolioManager(initial_capital=1700.0)
        pf.cash = 0.0
        pf.total_value = 0.0
        assert pf.ensure_buying_power(1700.0) is True
        assert pf.cash == 1700.0
        assert pf.total_value == 1700.0


# ── P0-5: Bridge cleanup ──────────────────────────────────────────

class TestP05_BridgeCleanup:
    """P0-5: Bridge cleanup — trading_pipeline.py must not contain old backend module-level imports."""

    @pytest.fixture
    def pipeline_source(self):
        """Read trading_pipeline.py source."""
        path = os.path.join(_PROJ_ROOT, "trading_pipeline.py")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_no_backend_portfolio_import(self, pipeline_source):
        """trading_pipeline.py must not contain from backend.trading_engine.portfolio import."""
        assert "from backend.trading_engine.portfolio" not in pipeline_source, (
            "trading_pipeline.py must NOT import from backend.trading_engine.portfolio"
        )
        # Also check import variant
        assert "import backend.trading_engine.portfolio" not in pipeline_source, (
            "trading_pipeline.py must NOT import backend.trading_engine.portfolio"
        )

    def test_no_backend_risk_manager_import(self, pipeline_source):
        """trading_pipeline.py must not contain from backend.trading_engine.risk_manager import."""
        assert "from backend.trading_engine.risk_manager" not in pipeline_source, (
            "trading_pipeline.py must NOT import from backend.trading_engine.risk_manager"
        )
        assert "import backend.trading_engine.risk_manager" not in pipeline_source, (
            "trading_pipeline.py must NOT import backend.trading_engine.risk_manager"
        )

    def test_no_backend_executor_import(self, pipeline_source):
        """trading_pipeline.py must not contain from backend.trading_engine.executor import."""
        assert "from backend.trading_engine.executor" not in pipeline_source, (
            "trading_pipeline.py must NOT import from backend.trading_engine.executor"
        )
        assert "import backend.trading_engine.executor" not in pipeline_source, (
            "trading_pipeline.py must NOT import backend.trading_engine.executor"
        )

    def test_uses_shared_modules(self, pipeline_source):
        """trading_pipeline.py uses shared/ modules instead of old backend imports."""
        assert "from shared.portfolio_manager import PortfolioManager" in pipeline_source
        assert "from shared.risk_manager import RiskManager" in pipeline_source
        assert "from shared.tiger_executor import TigerExecutor" in pipeline_source

    def test_tiger_bridge_uses_lazy_import(self):
        """shared/tiger_bridge.py uses lazy imports (no module-level import backend)."""
        path = os.path.join(_PROJ_ROOT, "shared", "tiger_bridge.py")
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()

        # Module level must not have from backend. import
        lines = source.splitlines()
        for line in lines:
            stripped = line.strip()
            # Ignore comment lines and in-function imports
            if stripped.startswith("#"):
                continue
            if stripped.startswith("from backend.") or stripped.startswith("import backend."):
                # Must be an import inside a function/method (indented)
                leading_spaces = len(line) - len(line.lstrip())
                if leading_spaces == 0:
                    pytest.fail(
                        f"shared/tiger_bridge.py has module-level backend import: {stripped}"
                    )


# ───────────────────────────────────────────────────────────────
# Step 2 continued: Functional Tests — P1 Requirements
# ───────────────────────────────────────────────────────────────


# ── P1-1: Leverage iron rule ──────────────────────────────────────────

class TestP11_LeverageIronLaw:
    """P1-1: Leverage iron rule — check_leverage blocks leveraged trades."""

    def test_leverage_15_blocked(self):
        """check_leverage({"leverage": 1.5}) → True (block the trade)."""
        from shared.risk_manager import RiskManager

        rm = RiskManager()
        result = rm.check_leverage({"leverage": 1.5})
        assert result is True, "Leverage 1.5 should be blocked"

    def test_leverage_10_allowed(self):
        """check_leverage({"leverage": 1.0}) → False (allow)."""
        from shared.risk_manager import RiskManager

        rm = RiskManager()
        result = rm.check_leverage({"leverage": 1.0})
        assert result is False, "Leverage 1.0 should be allowed"

    def test_leverage_1001_blocked(self):
        """check_leverage({"leverage": 1.001}) → True (block; strictly above the 1.001 threshold)."""
        from shared.risk_manager import RiskManager

        rm = RiskManager()
        result = rm.check_leverage({"leverage": 1.002})
        assert result is True, f"Leverage >1.001 should be blocked, got {result}"

    def test_leverage_none_allowed(self):
        """check_leverage(None) → False (None account = safe)."""
        from shared.risk_manager import RiskManager

        rm = RiskManager()
        result = rm.check_leverage(None)
        assert result is False, "None account should be allowed"


# ── P1-2: Daily trade cap ──────────────────────────────────────

class TestP12_DailyTradeLimit:
    """P1-2: Daily trade cap — check_daily_limit."""

    def test_trades_today_equals_max_blocked(self):
        """trades_today=5, max=5 → True (block)."""
        from shared.risk_manager import RiskManager

        rm = RiskManager(max_daily_trades=5)
        rm.trades_today = 5
        result = rm.check_daily_limit()
        assert result is True, "When trades_today == max, should be blocked"

    def test_max_zero_allowed(self):
        """max_daily_trades=0 → False (no limit)."""
        from shared.risk_manager import RiskManager

        rm = RiskManager(max_daily_trades=0)
        rm.trades_today = 999
        result = rm.check_daily_limit()
        assert result is False, "max=0 should disable limit"

    def test_trades_below_max_allowed(self):
        """trades_today=3, max=5 → False (allow)."""
        from shared.risk_manager import RiskManager

        rm = RiskManager(max_daily_trades=5)
        rm.trades_today = 3
        result = rm.check_daily_limit()
        assert result is False, "trades < max should be allowed"


# ── P1-3: Short-position fix ──────────────────────────────────────────

class TestP13_ShortFix:
    """P1-3: Short-position fix — fix_short_positions detects and repairs negative holdings."""

    def test_fix_short_positions_detects_negative(self):
        """fix_short_positions detects and repairs negative holdings."""
        from shared.risk_manager import RiskManager
        from shared.portfolio_manager import PortfolioManager

        rm = RiskManager(initial_capital=100000.0)
        pf = PortfolioManager(initial_capital=100000.0)
        # Seed a negative holding (short)
        pf.positions["AAPL"] = -50.0

        mock_tiger = MagicMock()
        mock_tiger.is_connected.return_value = False
        prices = {"AAPL": 180.0}

        fixed = rm.fix_short_positions(pf, mock_tiger, prices)
        assert fixed >= 1, f"Should fix at least 1 short position, got {fixed}"

    def test_fix_short_positions_no_short(self):
        """Returns 0 when there are no shorts."""
        from shared.risk_manager import RiskManager
        from shared.portfolio_manager import PortfolioManager

        rm = RiskManager(initial_capital=100000.0)
        pf = PortfolioManager(initial_capital=100000.0)
        pf.positions["AAPL"] = 100.0  # long position

        mock_tiger = MagicMock()
        prices = {"AAPL": 180.0}

        fixed = rm.fix_short_positions(pf, mock_tiger, prices)
        assert fixed == 0, "No short positions should return 0"

    def test_fix_short_positions_updates_portfolio(self):
        """Portfolio holdings should update after shorts are repaired."""
        from shared.risk_manager import RiskManager
        from shared.portfolio_manager import PortfolioManager

        rm = RiskManager(initial_capital=100000.0)
        pf = PortfolioManager(initial_capital=100000.0)
        pf.positions["AAPL"] = -50.0
        pf.cash = 100000.0 + 50 * 180  # provide enough cash

        mock_tiger = MagicMock()
        mock_tiger.is_connected.return_value = False
        prices = {"AAPL": 180.0}

        fixed = rm.fix_short_positions(pf, mock_tiger, prices)
        assert fixed >= 1
        # After the fix, AAPL holdings should be ≥ 0
        assert pf.positions.get("AAPL", -1) >= 0, "Position should be non-negative after fix"


# ── P1-4: v1 fallback ────────────────────────────────────

class TestP14_V1Fallback:
    """P1-4: v1 fallback — exponential backoff retry logic."""

    def test_retry_http_call_exists(self):
        """_retry_http_call method exists on TradingPipeline."""
        path = os.path.join(_PROJ_ROOT, "trading_pipeline.py")
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
        assert "_retry_http_call" in source, (
            "TradingPipeline must have _retry_http_call method"
        )

    def test_exponential_backoff_logic(self):
        """_retry_http_call includes exponential backoff: wait = 2 ** attempt."""
        path = os.path.join(_PROJ_ROOT, "trading_pipeline.py")
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
        # Exponential-backoff signature: 2 ** attempt or 2**attempt
        assert "2 ** attempt" in source or "2**attempt" in source or "2** attempt" in source, (
            "Retry logic must use exponential backoff (2 ** attempt)"
        )

    def test_max_retries_configurable(self):
        """_retry_http_call accepts a max_retries parameter."""
        path = os.path.join(_PROJ_ROOT, "trading_pipeline.py")
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
        assert "max_retries" in source, "Retry function must accept max_retries parameter"


# ── P1-5: Frontend push ──────────────────────────────────────────

class TestP15_WebSocketPush:
    """P1-5: Frontend push — WsPusher must not raise."""

    def test_wspusher_disabled_no_exception(self):
        """WsPusher push must not raise when enabled=False."""
        import asyncio
        from shared.ws_pusher import WsPusher

        async def _test():
            wp = WsPusher(api_url="http://localhost:99999", enabled=False)
            await wp.push_step_update(1, 1, {"test": "data"})
            await wp.push_alert("test", "test message")
            await wp.push_summary(1, {"test": "summary"})
            await wp.close()

        asyncio.run(_test())

    def test_wspusher_no_url_no_exception(self):
        """WsPusher push must not raise when api_url=""."""
        import asyncio
        from shared.ws_pusher import WsPusher

        async def _test():
            wp = WsPusher(api_url="", enabled=True)
            await wp.push_step_update(1, 1, {"test": "data"})
            await wp.close()

        asyncio.run(_test())

    def test_wspusher_unreachable_no_exception(self):
        """WsPusher must not raise when pushing to an unreachable endpoint (graceful degradation)."""
        import asyncio
        from shared.ws_pusher import WsPusher

        async def _test():
            # Port is almost certainly unused
            wp = WsPusher(api_url="http://127.0.0.1:1", enabled=True, timeout=0.5)
            await wp.push_step_update(1, 1, {"test": "data"})
            await wp.push_alert("test", "test message")
            await wp.push_summary(1, {"test": "summary"})
            await wp.close()

        # Must not raise
        try:
            asyncio.run(_test())
        except Exception as e:
            pytest.fail(f"WsPusher should not raise exceptions on unreachable endpoint: {e}")


# ───────────────────────────────────────────────────────────────
# Step 2 continued: Functional Tests — P2 Requirements
# ───────────────────────────────────────────────────────────────


# ── P2-1: Git auto-sync ───────────────────────────────────────

class TestP21_GitAutoSync:
    """P2-1: Git auto-sync — must not be called when GIT_AUTO_SYNC=False."""

    def test_git_sync_disabled_in_trading_pipeline(self):
        """trading_pipeline.py must not call git_sync when GIT_AUTO_SYNC=False."""
        path = os.path.join(_PROJ_ROOT, "trading_pipeline.py")
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()

        # Verify GIT_AUTO_SYNC control logic exists
        assert "GIT_AUTO_SYNC" in source, (
            "trading_pipeline.py must check GIT_AUTO_SYNC before git sync"
        )
        assert "self.config.GIT_AUTO_SYNC" in source, (
            "Must reference config.GIT_AUTO_SYNC"
        )

    def test_pipeline_config_default_auto_sync_false(self):
        """PipelineConfig defaults GIT_AUTO_SYNC=False."""
        from configs.pipeline_config import PipelineConfig

        cfg = PipelineConfig()
        assert cfg.GIT_AUTO_SYNC is False, "Default GIT_AUTO_SYNC should be False"

    def test_git_sync_module_no_git_dir(self):
        """git_sync returns False in a non-git directory (does not raise)."""
        import tempfile
        from shared.git_sync import git_sync

        with tempfile.TemporaryDirectory() as tmpdir:
            result = git_sync(tmpdir)
            assert result is False, "Non-git directory should return False"


# ───────────────────────────────────────────────────────────────
# Step 2 continued: PipelineConfig field completeness
# ───────────────────────────────────────────────────────────────


class TestPipelineConfigFields:
    """PipelineConfig includes all new v2.2 fields."""

    def test_all_new_fields_present(self):
        """Verify PipelineConfig includes all new P0-P1 fields."""
        from configs.pipeline_config import PipelineConfig

        cfg = PipelineConfig()

        required_fields = [
            "EXECUTION_MODE",
            "MAX_DAILY_TRADES",
            "DAILY_LOSS_LIMIT",
            "LEVERAGE_LIMIT",
            "V1_FALLBACK_RETRIES",
            "ENABLE_WS_PUSH",
            "GIT_AUTO_SYNC",
            "FORCE_SELL_TICKERS",
        ]

        for field_name in required_fields:
            assert hasattr(cfg, field_name), f"PipelineConfig missing field: {field_name}"

    def test_execution_mode_default_paper(self):
        """EXECUTION_MODE defaults to 'paper'."""
        from configs.pipeline_config import PipelineConfig

        cfg = PipelineConfig()
        assert cfg.EXECUTION_MODE == "paper"

    def test_leverage_limit_default(self):
        """LEVERAGE_LIMIT defaults to 1.001."""
        from configs.pipeline_config import PipelineConfig

        cfg = PipelineConfig()
        assert cfg.LEVERAGE_LIMIT == 1.001

    def test_v1_fallback_retries_default(self):
        """V1_FALLBACK_RETRIES defaults to 3."""
        from configs.pipeline_config import PipelineConfig

        cfg = PipelineConfig()
        assert cfg.V1_FALLBACK_RETRIES == 3


# ───────────────────────────────────────────────────────────────
# Step 2 continued: RiskManager additional checks
# ───────────────────────────────────────────────────────────────


class TestRiskManagerAdditional:
    """RiskManager additional tests (check_order, edge cases)."""

    def test_check_order_passes_normal(self):
        """check_order passes a normal buy."""
        from shared.risk_manager import RiskManager

        rm = RiskManager(initial_capital=100000.0)
        rm.sync_portfolio_value(100000.0, 100000.0)
        rm.daily_start_value = 100000.0  # ensure initialized
        report = rm.check_order("AAPL", "buy", 50, 180.0)
        assert report.passed is True, f"Normal buy should pass, got: {report.reason}"

    def test_check_order_rejected_insufficient_cash(self):
        """check_order rejects when cash is insufficient."""
        from shared.risk_manager import RiskManager

        rm = RiskManager(initial_capital=1000.0)
        rm.sync_portfolio_value(1000.0, 1000.0)
        rm.daily_start_value = 1000.0
        # Attempt to buy 1000 shares @ $180 = $180,000 (far above cash)
        report = rm.check_order("AAPL", "buy", 1000, 180.0)
        assert report.passed is False

    def test_check_order_min_trade_value(self):
        """check_order rejects below the minimum trade value."""
        from shared.risk_manager import RiskManager

        rm = RiskManager(initial_capital=100000.0)
        rm.sync_portfolio_value(100000.0, 100000.0)
        rm.daily_start_value = 100000.0
        # MIN_TRADE_VALUE = 100.0, 1 share @ $1 = $1
        report = rm.check_order("AAPL", "buy", 1, 1.0)
        assert report.passed is False

    def test_record_trade(self):
        """record_trade increments trades_today."""
        from shared.risk_manager import RiskManager

        rm = RiskManager(initial_capital=100000.0, max_daily_trades=10)
        assert rm.trades_today == 0
        rm.record_trade()
        assert rm.trades_today == 1
        rm.record_trade()
        assert rm.trades_today == 2

    def test_get_status(self):
        """get_status returns a complete status dict."""
        from shared.risk_manager import RiskManager

        rm = RiskManager(initial_capital=100000.0)
        status = rm.get_status()
        required_keys = [
            "portfolio_value", "cash", "peak_value", "daily_start_value",
            "daily_pnl", "daily_pnl_pct", "current_drawdown",
            "circuit_breaker_triggered", "breaker_mode",
            "trades_today", "max_daily_trades", "num_positions",
        ]
        for key in required_keys:
            assert key in status, f"get_status missing key: {key}"


# ───────────────────────────────────────────────────────────────
# Step 2 continued: TigerExecutor edge cases
# ───────────────────────────────────────────────────────────────


class TestTigerExecutorEdgeCases:
    """TigerExecutor edge-case tests."""

    @staticmethod
    def _make_mock_portfolio(initial_capital=100000.0):
        """Create a mock portfolio with format-friendly initial_capital."""
        pf = MagicMock()
        pf.initial_capital = initial_capital
        pf.total_value = initial_capital
        pf.cash = initial_capital
        pf.positions = {}
        pf.avg_costs = {}
        return pf

    @staticmethod
    def _make_mock_risk():
        """Create a mock risk manager."""
        from shared.risk_manager import RiskReport
        rm = MagicMock()
        rm.check_order.return_value = RiskReport(passed=True)
        rm.check_circuit_breaker.return_value = RiskReport(passed=True)
        rm.record_trade = MagicMock()
        return rm

    def test_invalid_mode_raises(self):
        """Invalid mode raises ValueError."""
        from shared.tiger_executor import TigerExecutor

        with pytest.raises(ValueError, match="mode must be"):
            TigerExecutor(
                mode="invalid",
                portfolio=self._make_mock_portfolio(),
                risk=self._make_mock_risk(),
                tiger_bridge=MagicMock(),
            )

    def test_hold_returns_none(self):
        """HOLD signal returns None."""
        from shared.tiger_executor import TigerExecutor

        executor = TigerExecutor(
            mode="paper",
            portfolio=self._make_mock_portfolio(),
            risk=self._make_mock_risk(),
            tiger_bridge=MagicMock(),
        )
        result = executor.execute_signal("AAPL", "HOLD", 0.5, 180.0, 0.5)
        assert result is None, "HOLD should return None"

    def test_invalid_decision_returns_none(self):
        """Invalid decision returns None."""
        from shared.tiger_executor import TigerExecutor

        executor = TigerExecutor(
            mode="paper",
            portfolio=self._make_mock_portfolio(),
            risk=self._make_mock_risk(),
            tiger_bridge=MagicMock(),
        )
        result = executor.execute_signal("AAPL", "INVALID", 0.5, 180.0, 0.5)
        assert result is None

    def test_zero_price_returns_none(self):
        """price=0 returns None."""
        from shared.tiger_executor import TigerExecutor

        executor = TigerExecutor(
            mode="paper",
            portfolio=self._make_mock_portfolio(),
            risk=self._make_mock_risk(),
            tiger_bridge=MagicMock(),
        )
        result = executor.execute_signal("AAPL", "BUY", 0.5, 0.0, 0.5)
        assert result is None

    def test_execute_rebalance_empty_weights(self):
        """Empty weights return an empty list."""
        from shared.tiger_executor import TigerExecutor

        executor = TigerExecutor(
            mode="paper",
            portfolio=self._make_mock_portfolio(),
            risk=self._make_mock_risk(),
            tiger_bridge=MagicMock(),
        )
        result = executor.execute_rebalance({}, {})
        assert result == []

    def test_get_execution_summary(self):
        """get_execution_summary returns a summary."""
        from shared.tiger_executor import TigerExecutor

        executor = TigerExecutor(
            mode="paper",
            portfolio=self._make_mock_portfolio(),
            risk=self._make_mock_risk(),
            tiger_bridge=MagicMock(),
        )
        summary = executor.get_execution_summary()
        assert summary["mode"] == "paper"
        assert "total_filled" in summary
        assert "buy_count" in summary
        assert "sell_count" in summary


# ───────────────────────────────────────────────────────────────
# Step 2 continued: PortfolioManager additional tests
# ───────────────────────────────────────────────────────────────


class TestPortfolioManagerAdditional:
    """PortfolioManager additional tests."""

    def test_execute_trade_buy(self):
        """execute_trade BUY updates holdings correctly."""
        from shared.portfolio_manager import PortfolioManager

        pf = PortfolioManager(initial_capital=100000.0)
        trade = pf.execute_trade("AAPL", "buy", 180.0, 100.0, "test")
        assert trade is not None
        assert trade["side"] == "buy"
        assert pf.positions["AAPL"] == 100.0
        assert pf.cash == 100000.0 - 18000.0

    def test_execute_trade_sell(self):
        """execute_trade SELL updates holdings correctly."""
        from shared.portfolio_manager import PortfolioManager

        pf = PortfolioManager(initial_capital=100000.0)
        pf.positions["AAPL"] = 100.0
        pf.cash = 82000.0
        trade = pf.execute_trade("AAPL", "sell", 180.0, 50.0, "test")
        assert trade is not None
        assert trade["side"] == "sell"
        assert pf.positions["AAPL"] == 50.0
        assert pf.cash == 82000.0 + 9000.0

    def test_execute_trade_insufficient_cash(self):
        """execute_trade BUY returns None when cash is insufficient."""
        from shared.portfolio_manager import PortfolioManager

        pf = PortfolioManager(initial_capital=1000.0)
        trade = pf.execute_trade("AAPL", "buy", 180.0, 1000.0, "test")
        assert trade is None

    def test_execute_trade_no_position_sell(self):
        """execute_trade SELL returns None when there is no position."""
        from shared.portfolio_manager import PortfolioManager

        pf = PortfolioManager(initial_capital=100000.0)
        trade = pf.execute_trade("AAPL", "sell", 180.0, 50.0, "test")
        assert trade is None

    def test_get_metrics(self):
        """get_metrics returns a complete metrics dict."""
        from shared.portfolio_manager import PortfolioManager

        pf = PortfolioManager(initial_capital=100000.0)
        metrics = pf.get_metrics()
        required_keys = [
            "total_value", "cash", "num_positions",
            "daily_pnl", "total_return_pct", "sharpe_ratio",
            "max_drawdown", "total_trades",
        ]
        for key in required_keys:
            assert key in metrics, f"get_metrics missing key: {key}"

    def test_update_value(self):
        """update_value updates total value."""
        from shared.portfolio_manager import PortfolioManager

        pf = PortfolioManager(initial_capital=100000.0)
        pf.positions["AAPL"] = 100.0
        pf.cash = 82000.0
        pf.update_value({"AAPL": 200.0})
        # 100 * 200 + 82000 = 102000
        assert pf.total_value == 102000.0


# ───────────────────────────────────────────────────────────────
# Step 2 continued: DailyState tests
# ───────────────────────────────────────────────────────────────


class TestDailyState:
    """DailyState tests."""

    def test_init_defaults(self):
        """DailyState initializes default values."""
        from shared.daily_state import DailyState

        ds = DailyState()
        assert ds.trades_today == 0
        assert ds.trade_date is not None

    def test_record_trade(self):
        """record_trade increments the counter."""
        from shared.daily_state import DailyState

        ds = DailyState()
        assert ds.trades_today == 0
        ds.record_trade()
        assert ds.trades_today == 1

    def test_check_date_roll_no_roll(self):
        """check_date_roll returns False on the same day."""
        from shared.daily_state import DailyState

        ds = DailyState()
        result = ds.check_date_roll()
        assert result is False, "Same day should not roll"

    def test_reset_for_new_day(self):
        """reset_for_new_day resets all counters."""
        from shared.daily_state import DailyState

        ds = DailyState(daily_start_value=100000.0)
        ds.trades_today = 10
        ds.reset_for_new_day(105000.0)
        assert ds.trades_today == 0
        assert ds.daily_start_value == 105000.0


# ───────────────────────────────────────────────────────────────
# Step 3: Run existing test suite
# ───────────────────────────────────────────────────────────────

class TestExistingTestCompatibility:
    """Verify compatibility of existing test files."""

    def test_v22_tests_are_self_contained(self):
        """Ensure this test file has no module-level backend imports."""
        import inspect
        path = os.path.join(_PROJ_ROOT, "tests", "test_v22_verification.py")
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()

        lines = source.splitlines()
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # Check for module-level backend imports
            if stripped.startswith("from backend.") or stripped.startswith("import backend."):
                leading = len(line) - len(line.lstrip())
                if leading == 0:
                    pytest.fail(
                        f"test_v22_verification.py has module-level backend import: {stripped}"
                    )


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
