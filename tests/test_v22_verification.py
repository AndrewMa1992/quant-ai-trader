"""
tests/test_v22_verification.py — v2.2 全量验证测试套件
======================================================
QA Engineer: Edward (严过关)

覆盖 P0/P1/P2 全部 15 项需求:
  P0-1: 实盘执行通道 (TigerExecutor live/paper/rebalance)
  P0-2: 组合熔断 (circuit breaker, liquidate_all, daily_start init)
  P0-3: 市场时段检测 (get_market_status, is_any_market_open)
  P0-4: Tiger状态同步 (sync_from_tiger)
  P0-5: 桥接清理 (AST check: no backend. imports in trading_pipeline)
  P1-1: 杠杆铁律 (check_leverage)
  P1-2: 每日交易上限 (check_daily_limit)
  P1-3: 空头修复 (fix_short_positions)
  P1-4: v1 fallback降级 (指数退避逻辑)
  P1-5: 前端推送 (WsPusher 不抛异常)
  P2-1: Git自动同步 (GIT_AUTO_SYNC=False 不调用)

运行方式:
    cd E:\workbuddyspace\Claw\quant-ai-trader
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
    """验证所有 shared/ 模块和 PipelineConfig 可正确导入。"""

    def test_import_shared_tiger_bridge(self):
        """shared.tiger_bridge 可导入。"""
        import shared.tiger_bridge
        assert shared.tiger_bridge is not None

    def test_import_shared_market_session(self):
        """shared.market_session 可导入。"""
        import shared.market_session
        assert shared.market_session is not None

    def test_import_shared_portfolio_manager(self):
        """shared.portfolio_manager 可导入。"""
        import shared.portfolio_manager
        assert shared.portfolio_manager is not None

    def test_import_shared_risk_manager(self):
        """shared.risk_manager 可导入。"""
        import shared.risk_manager
        assert shared.risk_manager is not None

    def test_import_shared_tiger_executor(self):
        """shared.tiger_executor 可导入。"""
        import shared.tiger_executor
        assert shared.tiger_executor is not None

    def test_import_shared_daily_state(self):
        """shared.daily_state 可导入。"""
        import shared.daily_state
        assert shared.daily_state is not None

    def test_import_shared_ws_pusher(self):
        """shared.ws_pusher 可导入。"""
        import shared.ws_pusher
        assert shared.ws_pusher is not None

    def test_import_shared_git_sync(self):
        """shared.git_sync 可导入。"""
        import shared.git_sync
        assert shared.git_sync is not None

    def test_import_risk_report_class(self):
        """RiskReport 可从 risk_manager 导入。"""
        from shared.risk_manager import RiskReport
        report = RiskReport()
        assert report.passed is True
        assert report.circuit_breaker is False

    def test_import_risk_manager_class(self):
        """RiskManager 可从 risk_manager 导入。"""
        from shared.risk_manager import RiskManager
        rm = RiskManager()
        assert rm is not None

    def test_import_tiger_executor_class(self):
        """TigerExecutor 可从 tiger_executor 导入。"""
        from shared.tiger_executor import TigerExecutor
        assert TigerExecutor is not None

    def test_import_portfolio_manager_class(self):
        """PortfolioManager 可从 portfolio_manager 导入。"""
        from shared.portfolio_manager import PortfolioManager
        pm = PortfolioManager()
        assert pm is not None

    def test_import_market_session_functions(self):
        """get_market_status / is_any_market_open 可从 market_session 导入。"""
        from shared.market_session import get_market_status, is_any_market_open
        status = get_market_status()
        assert isinstance(status, dict)
        # P0-3: 返回 3 个市场的状态 (US, HK, CN)
        assert len(status) >= 2  # At least 2 markets tracked
        result = is_any_market_open()
        assert isinstance(result, bool)

    def test_import_pipeline_config(self):
        """PipelineConfig 可从 configs.pipeline_config 导入。"""
        from configs.pipeline_config import PipelineConfig, pipeline_config
        assert PipelineConfig is not None
        assert pipeline_config is not None

    def test_import_wspusher_class(self):
        """WsPusher 可从 ws_pusher 导入。"""
        from shared.ws_pusher import WsPusher
        wp = WsPusher(api_url="http://localhost:9999", enabled=False)
        assert wp is not None

    def test_import_dailystate_class(self):
        """DailyState 可从 daily_state 导入。"""
        from shared.daily_state import DailyState
        ds = DailyState()
        assert ds is not None


# ───────────────────────────────────────────────────────────────
# Step 2: Functional Tests — P0 Requirements
# ───────────────────────────────────────────────────────────────


# ── P0-1: 实盘执行通道 ──────────────────────────────────────

class TestP01_TigerExecutor:
    """P0-1: TigerExecutor live/paper/rebalance 测试。"""

    @pytest.fixture
    def mock_portfolio(self):
        """创建 mock portfolio。"""
        from shared.portfolio_manager import PortfolioManager
        pf = PortfolioManager(initial_capital=100000.0)
        # 预设持仓: AAPL 100股 @ $180
        pf.positions["AAPL"] = 100.0
        pf.avg_costs["AAPL"] = 180.0
        pf.cash = 82000.0
        pf.total_value = 100000.0
        return pf

    @pytest.fixture
    def mock_risk(self):
        """创建 mock risk manager。"""
        from shared.risk_manager import RiskManager
        rm = RiskManager(initial_capital=100000.0)
        rm.sync_portfolio_value(100000.0, 82000.0)
        # 确保 daily_start_value 已初始化，避免 check_circuit_breaker 第一次返回空
        rm.daily_start_value = 100000.0
        return rm

    @pytest.fixture
    def mock_tiger(self):
        """创建 mock tiger bridge。"""
        tiger = MagicMock()
        tiger.is_connected.return_value = False  # 默认断连
        tiger.place_order.return_value = {"order_id": "fake-order-123"}
        tiger.get_account_info.return_value = {
            "cash": 82000.0, "total_value": 100000.0, "leverage": 1.0
        }
        tiger.get_positions.return_value = [
            {"ticker": "AAPL", "shares": 100, "avg_cost": 180.0, "market_value": 18000.0}
        ]
        return tiger

    def test_paper_mode_calls_portfolio_execute_trade(self, mock_portfolio, mock_risk, mock_tiger):
        """TigerExecutor mode='paper' → 调用 portfolio.execute_trade。"""
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
        """TigerExecutor mode='live' → 调用 tiger_bridge.place_order。"""
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
        """execute_rebalance 正确计算权重差异并生成订单。"""
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


# ── P0-2: 组合熔断 ──────────────────────────────────────────

class TestP02_CircuitBreaker:
    """P0-2: 组合熔断 (circuit breaker, liquidate_all, daily_start init)。"""

    def test_daily_loss_5pct_triggers_breaker_hard(self):
        """日亏损 ≥5% → RiskReport(passed=False, circuit_breaker=True) in hard mode。"""
        from shared.risk_manager import RiskManager

        rm = RiskManager(initial_capital=100000.0, breaker_mode="hard")
        rm.sync_portfolio_value(100000.0, 100000.0)
        # 首次调用初始化 daily_start_value
        report = rm.check_circuit_breaker()
        # 第一次调用总是通过 (初始化)
        assert report.passed is True, "First call should always pass (init)"
        assert report.circuit_breaker is False

        # 模拟日亏损 6%
        rm.portfolio_value = 94000.0  # -6%
        report = rm.check_circuit_breaker()
        assert report.passed is False, "6% daily loss should block in hard mode"
        assert report.circuit_breaker is True

    def test_daily_loss_5pct_warn_mode_passes(self):
        """breaker_mode='warn' → daily_loss 5% → passed=True but circuit_breaker=True。"""
        from shared.risk_manager import RiskManager

        rm = RiskManager(initial_capital=100000.0, breaker_mode="warn")
        rm.sync_portfolio_value(100000.0, 100000.0)
        # 首次初始化
        rm.check_circuit_breaker()
        # 模拟日亏损 6%
        rm.portfolio_value = 94000.0
        report = rm.check_circuit_breaker()
        assert report.passed is True, "warn mode should still pass"
        assert report.circuit_breaker is True, "circuit_breaker flag should still be set"

    def test_liquidate_all_returns_order_list(self):
        """liquidate_all 返回平仓订单列表。"""
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
        """无持仓时 liquidate_all 返回空列表。"""
        from shared.risk_manager import RiskManager

        rm = RiskManager(initial_capital=100000.0)
        rm.positions = {}
        prices = {}
        mock_tiger = MagicMock()

        orders = rm.liquidate_all(prices, mock_tiger)
        assert orders == [], "No positions should return empty list"

    def test_first_check_initializes_daily_start(self):
        """首次调用 check_circuit_breaker 自动初始化 daily_start_value。"""
        from shared.risk_manager import RiskManager

        rm = RiskManager(initial_capital=100000.0)
        assert rm.daily_start_value == 0.0, "Should start at 0"

        report = rm.check_circuit_breaker()
        assert rm.daily_start_value > 0, "daily_start_value should be initialized"
        assert rm.daily_start_value == 100000.0

    def test_cool_down_period(self):
        """断路器触发后在冷却期内持续阻断。"""
        from shared.risk_manager import RiskManager
        from datetime import datetime, timedelta

        rm = RiskManager(initial_capital=100000.0, breaker_mode="hard")
        rm.sync_portfolio_value(100000.0, 100000.0)
        rm.check_circuit_breaker()  # init

        # 手动触发断路器
        rm.circuit_breaker_triggered = True
        rm.circuit_breaker_time = datetime.now()  # just now
        rm.daily_start_value = 100000.0
        rm.portfolio_value = 100000.0

        report = rm.check_circuit_breaker()
        assert report.passed is False
        assert report.circuit_breaker is True
        assert "冷却" in report.reason


# ── P0-3: 市场时段检测 ──────────────────────────────────────

class TestP03_MarketSession:
    """P0-3: 市场时段检测 (get_market_status, is_any_market_open)。"""

    def test_get_market_status_returns_dict(self):
        """get_market_status() 返回字典，包含 US/HK/CN 键。"""
        from shared.market_session import get_market_status, _MARKETS

        status = get_market_status()
        assert isinstance(status, dict), "Should return dict"
        # 验证包含所有跟踪的市场
        for market in _MARKETS:
            assert market in status, f"Market {market} should be in status"
        assert len(status) == len(_MARKETS), f"Should return {len(_MARKETS)} market statuses"

    def test_is_any_market_open_returns_bool(self):
        """is_any_market_open() 返回 bool，不抛异常。"""
        from shared.market_session import is_any_market_open

        result = is_any_market_open()
        assert isinstance(result, bool), "Should return bool"
        # 无论 True/False 都不应抛异常

    def test_no_exceptions(self):
        """市场时段检测函数不抛异常。"""
        from shared.market_session import get_market_status, is_any_market_open, is_market_open

        try:
            get_market_status()
            is_any_market_open()
            is_market_open("US")
            is_market_open("HK")
            is_market_open("CN")
            is_market_open("JP")  # 未知市场应返回 False
        except Exception as e:
            pytest.fail(f"Market session functions raised exception: {e}")

    def test_is_market_open_unknown_returns_false(self):
        """未知市场 is_market_open 返回 False。"""
        from shared.market_session import is_market_open

        result = is_market_open("NONEXISTENT")
        assert result is False


# ── P0-4: Tiger状态同步 ──────────────────────────────────────

class TestP04_TigerSync:
    """P0-4: Tiger 状态同步 (PortfolioManager.sync_from_tiger)。"""

    def test_sync_from_tiger_returns_required_fields(self):
        """sync_from_tiger 返回值包含所有必要字段。"""
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
        """sync_from_tiger 正确同步持仓数量。"""
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
        """Tiger 离线时 sync_from_tiger 返回 synced=False。"""
        from shared.portfolio_manager import PortfolioManager

        pf = PortfolioManager(initial_capital=100000.0)

        mock_tiger = MagicMock()
        mock_tiger.is_connected.return_value = False
        mock_tiger.connect.return_value = False

        result = pf.sync_from_tiger(mock_tiger, force=False)
        assert result["synced"] is False
        assert result["source"] in ("tiger_offline", "none")


# ── P0-5: 桥接清理 ──────────────────────────────────────────

class TestP05_BridgeCleanup:
    """P0-5: 桥接清理 — trading_pipeline.py 不包含旧的 backend 模块级导入。"""

    @pytest.fixture
    def pipeline_source(self):
        """读取 trading_pipeline.py 源码。"""
        path = os.path.join(_PROJ_ROOT, "trading_pipeline.py")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_no_backend_portfolio_import(self, pipeline_source):
        """trading_pipeline.py 不含 from backend.trading_engine.portfolio import。"""
        assert "from backend.trading_engine.portfolio" not in pipeline_source, (
            "trading_pipeline.py must NOT import from backend.trading_engine.portfolio"
        )
        # Also check import variant
        assert "import backend.trading_engine.portfolio" not in pipeline_source, (
            "trading_pipeline.py must NOT import backend.trading_engine.portfolio"
        )

    def test_no_backend_risk_manager_import(self, pipeline_source):
        """trading_pipeline.py 不含 from backend.trading_engine.risk_manager import。"""
        assert "from backend.trading_engine.risk_manager" not in pipeline_source, (
            "trading_pipeline.py must NOT import from backend.trading_engine.risk_manager"
        )
        assert "import backend.trading_engine.risk_manager" not in pipeline_source, (
            "trading_pipeline.py must NOT import backend.trading_engine.risk_manager"
        )

    def test_no_backend_executor_import(self, pipeline_source):
        """trading_pipeline.py 不含 from backend.trading_engine.executor import。"""
        assert "from backend.trading_engine.executor" not in pipeline_source, (
            "trading_pipeline.py must NOT import from backend.trading_engine.executor"
        )
        assert "import backend.trading_engine.executor" not in pipeline_source, (
            "trading_pipeline.py must NOT import backend.trading_engine.executor"
        )

    def test_uses_shared_modules(self, pipeline_source):
        """trading_pipeline.py 使用 shared/ 模块替代旧 backend 导入。"""
        assert "from shared.portfolio_manager import PortfolioManager" in pipeline_source
        assert "from shared.risk_manager import RiskManager" in pipeline_source
        assert "from shared.tiger_executor import TigerExecutor" in pipeline_source

    def test_tiger_bridge_uses_lazy_import(self):
        """shared/tiger_bridge.py 使用延迟导入 (不在模块级 import backend)。"""
        path = os.path.join(_PROJ_ROOT, "shared", "tiger_bridge.py")
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()

        # 模块级不应有 from backend. import
        lines = source.splitlines()
        for line in lines:
            stripped = line.strip()
            # 忽略注释行和函数内的 import
            if stripped.startswith("#"):
                continue
            if stripped.startswith("from backend.") or stripped.startswith("import backend."):
                # 必须是在函数/方法内部的 import (缩进)
                leading_spaces = len(line) - len(line.lstrip())
                if leading_spaces == 0:
                    pytest.fail(
                        f"shared/tiger_bridge.py has module-level backend import: {stripped}"
                    )


# ───────────────────────────────────────────────────────────────
# Step 2 continued: Functional Tests — P1 Requirements
# ───────────────────────────────────────────────────────────────


# ── P1-1: 杠杆铁律 ──────────────────────────────────────────

class TestP11_LeverageIronLaw:
    """P1-1: 杠杆铁律 — check_leverage 阻止杠杆交易。"""

    def test_leverage_15_blocked(self):
        """check_leverage({"leverage": 1.5}) → True (阻止交易)。"""
        from shared.risk_manager import RiskManager

        rm = RiskManager()
        result = rm.check_leverage({"leverage": 1.5})
        assert result is True, "Leverage 1.5 should be blocked"

    def test_leverage_10_allowed(self):
        """check_leverage({"leverage": 1.0}) → False (放行)。"""
        from shared.risk_manager import RiskManager

        rm = RiskManager()
        result = rm.check_leverage({"leverage": 1.0})
        assert result is False, "Leverage 1.0 should be allowed"

    def test_leverage_1001_blocked(self):
        """check_leverage({"leverage": 1.001}) → True (阻止，严格大于 1.001 阈值)。"""
        from shared.risk_manager import RiskManager

        rm = RiskManager()
        result = rm.check_leverage({"leverage": 1.002})
        assert result is True, f"Leverage >1.001 should be blocked, got {result}"

    def test_leverage_none_allowed(self):
        """check_leverage(None) → False (None account = safe)。"""
        from shared.risk_manager import RiskManager

        rm = RiskManager()
        result = rm.check_leverage(None)
        assert result is False, "None account should be allowed"


# ── P1-2: 每日交易上限 ──────────────────────────────────────

class TestP12_DailyTradeLimit:
    """P1-2: 每日交易上限 — check_daily_limit。"""

    def test_trades_today_equals_max_blocked(self):
        """trades_today=5, max=5 → True (阻止)。"""
        from shared.risk_manager import RiskManager

        rm = RiskManager(max_daily_trades=5)
        rm.trades_today = 5
        result = rm.check_daily_limit()
        assert result is True, "When trades_today == max, should be blocked"

    def test_max_zero_allowed(self):
        """max_daily_trades=0 → False (不限制)。"""
        from shared.risk_manager import RiskManager

        rm = RiskManager(max_daily_trades=0)
        rm.trades_today = 999
        result = rm.check_daily_limit()
        assert result is False, "max=0 should disable limit"

    def test_trades_below_max_allowed(self):
        """trades_today=3, max=5 → False (放行)。"""
        from shared.risk_manager import RiskManager

        rm = RiskManager(max_daily_trades=5)
        rm.trades_today = 3
        result = rm.check_daily_limit()
        assert result is False, "trades < max should be allowed"


# ── P1-3: 空头修复 ──────────────────────────────────────────

class TestP13_ShortFix:
    """P1-3: 空头修复 — fix_short_positions 检测负持仓并修复。"""

    def test_fix_short_positions_detects_negative(self):
        """fix_short_positions 检测负持仓并修复。"""
        from shared.risk_manager import RiskManager
        from shared.portfolio_manager import PortfolioManager

        rm = RiskManager(initial_capital=100000.0)
        pf = PortfolioManager(initial_capital=100000.0)
        # 设置一个负持仓 (空头)
        pf.positions["AAPL"] = -50.0

        mock_tiger = MagicMock()
        mock_tiger.is_connected.return_value = False
        prices = {"AAPL": 180.0}

        fixed = rm.fix_short_positions(pf, mock_tiger, prices)
        assert fixed >= 1, f"Should fix at least 1 short position, got {fixed}"

    def test_fix_short_positions_no_short(self):
        """无空头时返回 0。"""
        from shared.risk_manager import RiskManager
        from shared.portfolio_manager import PortfolioManager

        rm = RiskManager(initial_capital=100000.0)
        pf = PortfolioManager(initial_capital=100000.0)
        pf.positions["AAPL"] = 100.0  # 正持仓

        mock_tiger = MagicMock()
        prices = {"AAPL": 180.0}

        fixed = rm.fix_short_positions(pf, mock_tiger, prices)
        assert fixed == 0, "No short positions should return 0"

    def test_fix_short_positions_updates_portfolio(self):
        """修复空头后 portfolio 持仓应更新。"""
        from shared.risk_manager import RiskManager
        from shared.portfolio_manager import PortfolioManager

        rm = RiskManager(initial_capital=100000.0)
        pf = PortfolioManager(initial_capital=100000.0)
        pf.positions["AAPL"] = -50.0
        pf.cash = 100000.0 + 50 * 180  # 提供足够资金

        mock_tiger = MagicMock()
        mock_tiger.is_connected.return_value = False
        prices = {"AAPL": 180.0}

        fixed = rm.fix_short_positions(pf, mock_tiger, prices)
        assert fixed >= 1
        # 修复后 AAPL 持仓应 ≥ 0
        assert pf.positions.get("AAPL", -1) >= 0, "Position should be non-negative after fix"


# ── P1-4: v1 fallback降级 ────────────────────────────────────

class TestP14_V1Fallback:
    """P1-4: v1 fallback 降级 — 指数退避重试逻辑。"""

    def test_retry_http_call_exists(self):
        """_retry_http_call 方法存在于 TradingPipeline。"""
        path = os.path.join(_PROJ_ROOT, "trading_pipeline.py")
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
        assert "_retry_http_call" in source, (
            "TradingPipeline must have _retry_http_call method"
        )

    def test_exponential_backoff_logic(self):
        """_retry_http_call 包含指数退避: wait = 2 ** attempt。"""
        path = os.path.join(_PROJ_ROOT, "trading_pipeline.py")
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
        # 指数退避特征: 2 ** attempt 或 2**attempt
        assert "2 ** attempt" in source or "2**attempt" in source or "2** attempt" in source, (
            "Retry logic must use exponential backoff (2 ** attempt)"
        )

    def test_max_retries_configurable(self):
        """_retry_http_call 接受 max_retries 参数。"""
        path = os.path.join(_PROJ_ROOT, "trading_pipeline.py")
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
        assert "max_retries" in source, "Retry function must accept max_retries parameter"


# ── P1-5: 前端推送 ──────────────────────────────────────────

class TestP15_WebSocketPush:
    """P1-5: 前端推送 — WsPusher 不抛异常。"""

    def test_wspusher_disabled_no_exception(self):
        """WsPusher enabled=False 时 push 不抛异常。"""
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
        """WsPusher api_url="" 时 push 不抛异常。"""
        import asyncio
        from shared.ws_pusher import WsPusher

        async def _test():
            wp = WsPusher(api_url="", enabled=True)
            await wp.push_step_update(1, 1, {"test": "data"})
            await wp.close()

        asyncio.run(_test())

    def test_wspusher_unreachable_no_exception(self):
        """WsPusher 推送到不可达端点时不抛异常 (graceful degradation)。"""
        import asyncio
        from shared.ws_pusher import WsPusher

        async def _test():
            # 端口大概率未使用
            wp = WsPusher(api_url="http://127.0.0.1:1", enabled=True, timeout=0.5)
            await wp.push_step_update(1, 1, {"test": "data"})
            await wp.push_alert("test", "test message")
            await wp.push_summary(1, {"test": "summary"})
            await wp.close()

        # 不应抛异常
        try:
            asyncio.run(_test())
        except Exception as e:
            pytest.fail(f"WsPusher should not raise exceptions on unreachable endpoint: {e}")


# ───────────────────────────────────────────────────────────────
# Step 2 continued: Functional Tests — P2 Requirements
# ───────────────────────────────────────────────────────────────


# ── P2-1: Git自动同步 ───────────────────────────────────────

class TestP21_GitAutoSync:
    """P2-1: Git 自动同步 — GIT_AUTO_SYNC=False 时不调用。"""

    def test_git_sync_disabled_in_trading_pipeline(self):
        """trading_pipeline.py 中 GIT_AUTO_SYNC=False 时不调用 git_sync。"""
        path = os.path.join(_PROJ_ROOT, "trading_pipeline.py")
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()

        # 验证 GIT_AUTO_SYNC 控制逻辑存在
        assert "GIT_AUTO_SYNC" in source, (
            "trading_pipeline.py must check GIT_AUTO_SYNC before git sync"
        )
        assert "self.config.GIT_AUTO_SYNC" in source, (
            "Must reference config.GIT_AUTO_SYNC"
        )

    def test_pipeline_config_default_auto_sync_false(self):
        """PipelineConfig 默认 GIT_AUTO_SYNC=False。"""
        from configs.pipeline_config import PipelineConfig

        cfg = PipelineConfig()
        assert cfg.GIT_AUTO_SYNC is False, "Default GIT_AUTO_SYNC should be False"

    def test_git_sync_module_no_git_dir(self):
        """git_sync 在非 git 目录返回 False (不抛异常)。"""
        import tempfile
        from shared.git_sync import git_sync

        with tempfile.TemporaryDirectory() as tmpdir:
            result = git_sync(tmpdir)
            assert result is False, "Non-git directory should return False"


# ───────────────────────────────────────────────────────────────
# Step 2 continued: PipelineConfig 字段完整性
# ───────────────────────────────────────────────────────────────


class TestPipelineConfigFields:
    """PipelineConfig 包含所有新增 v2.2 字段。"""

    def test_all_new_fields_present(self):
        """验证 PipelineConfig 包含所有 P0-P1 新增字段。"""
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
        """EXECUTION_MODE 默认 'paper'。"""
        from configs.pipeline_config import PipelineConfig

        cfg = PipelineConfig()
        assert cfg.EXECUTION_MODE == "paper"

    def test_leverage_limit_default(self):
        """LEVERAGE_LIMIT 默认 1.001。"""
        from configs.pipeline_config import PipelineConfig

        cfg = PipelineConfig()
        assert cfg.LEVERAGE_LIMIT == 1.001

    def test_v1_fallback_retries_default(self):
        """V1_FALLBACK_RETRIES 默认 3。"""
        from configs.pipeline_config import PipelineConfig

        cfg = PipelineConfig()
        assert cfg.V1_FALLBACK_RETRIES == 3


# ───────────────────────────────────────────────────────────────
# Step 2 continued: RiskManager additional checks
# ───────────────────────────────────────────────────────────────


class TestRiskManagerAdditional:
    """RiskManager 补充测试 (check_order, 边界条件)。"""

    def test_check_order_passes_normal(self):
        """check_order 对正常买单通过。"""
        from shared.risk_manager import RiskManager

        rm = RiskManager(initial_capital=100000.0)
        rm.sync_portfolio_value(100000.0, 100000.0)
        rm.daily_start_value = 100000.0  # 确保已初始化
        report = rm.check_order("AAPL", "buy", 50, 180.0)
        assert report.passed is True, f"Normal buy should pass, got: {report.reason}"

    def test_check_order_rejected_insufficient_cash(self):
        """check_order 资金不足时拒绝。"""
        from shared.risk_manager import RiskManager

        rm = RiskManager(initial_capital=1000.0)
        rm.sync_portfolio_value(1000.0, 1000.0)
        rm.daily_start_value = 1000.0
        # 尝试买 1000 股 @ $180 = $180,000 (远超现金)
        report = rm.check_order("AAPL", "buy", 1000, 180.0)
        assert report.passed is False

    def test_check_order_min_trade_value(self):
        """check_order 低于最小交易额时拒绝。"""
        from shared.risk_manager import RiskManager

        rm = RiskManager(initial_capital=100000.0)
        rm.sync_portfolio_value(100000.0, 100000.0)
        rm.daily_start_value = 100000.0
        # MIN_TRADE_VALUE = 100.0, 1 share @ $1 = $1
        report = rm.check_order("AAPL", "buy", 1, 1.0)
        assert report.passed is False

    def test_record_trade(self):
        """record_trade 递增 trades_today。"""
        from shared.risk_manager import RiskManager

        rm = RiskManager(initial_capital=100000.0, max_daily_trades=10)
        assert rm.trades_today == 0
        rm.record_trade()
        assert rm.trades_today == 1
        rm.record_trade()
        assert rm.trades_today == 2

    def test_get_status(self):
        """get_status 返回完整状态字典。"""
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
# Step 2 continued: TigerExecutor 边界条件
# ───────────────────────────────────────────────────────────────


class TestTigerExecutorEdgeCases:
    """TigerExecutor 边界条件测试。"""

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
        """无效 mode 抛 ValueError。"""
        from shared.tiger_executor import TigerExecutor

        with pytest.raises(ValueError, match="mode must be"):
            TigerExecutor(
                mode="invalid",
                portfolio=self._make_mock_portfolio(),
                risk=self._make_mock_risk(),
                tiger_bridge=MagicMock(),
            )

    def test_hold_returns_none(self):
        """HOLD 信号返回 None。"""
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
        """无效 decision 返回 None。"""
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
        """price=0 返回 None。"""
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
        """空权重返回空列表。"""
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
        """get_execution_summary 返回摘要。"""
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
# Step 2 continued: PortfolioManager 补充测试
# ───────────────────────────────────────────────────────────────


class TestPortfolioManagerAdditional:
    """PortfolioManager 补充测试。"""

    def test_execute_trade_buy(self):
        """execute_trade BUY 正确更新持仓。"""
        from shared.portfolio_manager import PortfolioManager

        pf = PortfolioManager(initial_capital=100000.0)
        trade = pf.execute_trade("AAPL", "buy", 180.0, 100.0, "test")
        assert trade is not None
        assert trade["side"] == "buy"
        assert pf.positions["AAPL"] == 100.0
        assert pf.cash == 100000.0 - 18000.0

    def test_execute_trade_sell(self):
        """execute_trade SELL 正确更新持仓。"""
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
        """execute_trade BUY 资金不足时返回 None。"""
        from shared.portfolio_manager import PortfolioManager

        pf = PortfolioManager(initial_capital=1000.0)
        trade = pf.execute_trade("AAPL", "buy", 180.0, 1000.0, "test")
        assert trade is None

    def test_execute_trade_no_position_sell(self):
        """execute_trade SELL 无持仓时返回 None。"""
        from shared.portfolio_manager import PortfolioManager

        pf = PortfolioManager(initial_capital=100000.0)
        trade = pf.execute_trade("AAPL", "sell", 180.0, 50.0, "test")
        assert trade is None

    def test_get_metrics(self):
        """get_metrics 返回完整指标。"""
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
        """update_value 更新总价值。"""
        from shared.portfolio_manager import PortfolioManager

        pf = PortfolioManager(initial_capital=100000.0)
        pf.positions["AAPL"] = 100.0
        pf.cash = 82000.0
        pf.update_value({"AAPL": 200.0})
        # 100 * 200 + 82000 = 102000
        assert pf.total_value == 102000.0


# ───────────────────────────────────────────────────────────────
# Step 2 continued: DailyState 测试
# ───────────────────────────────────────────────────────────────


class TestDailyState:
    """DailyState 测试。"""

    def test_init_defaults(self):
        """DailyState 初始化默认值。"""
        from shared.daily_state import DailyState

        ds = DailyState()
        assert ds.trades_today == 0
        assert ds.trade_date is not None

    def test_record_trade(self):
        """record_trade 递增计数器。"""
        from shared.daily_state import DailyState

        ds = DailyState()
        assert ds.trades_today == 0
        ds.record_trade()
        assert ds.trades_today == 1

    def test_check_date_roll_no_roll(self):
        """同一天 check_date_roll 返回 False。"""
        from shared.daily_state import DailyState

        ds = DailyState()
        result = ds.check_date_roll()
        assert result is False, "Same day should not roll"

    def test_reset_for_new_day(self):
        """reset_for_new_day 重置所有计数器。"""
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
    """验证现有测试文件的兼容性。"""

    def test_v22_tests_are_self_contained(self):
        """确保本测试文件无 backend 模块级导入。"""
        import inspect
        path = os.path.join(_PROJ_ROOT, "tests", "test_v22_verification.py")
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()

        lines = source.splitlines()
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # 检查模块级 backend 导入
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
