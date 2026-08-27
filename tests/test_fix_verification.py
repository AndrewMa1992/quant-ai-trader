"""
tests/test_fix_verification.py — QA verification for 4 bug fixes.

Tests cover:
  1. GAT stub model attribute (Issue #1: AttributeError fix)
  2. fuse_signals KeyError defense (Issue #2: strategy.py & executor.py)
  3. Hardcoded token removal in push scripts (Issue #3)
  4. Tiger sync_all_to_db graceful degradation (Issue #4)
  5. daemon_forever.bat syntax check
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pytest

# ── Issue 1: GAT Stub Model Attribute ────────────────────────


class TestGATStubModelAttribute:
    """Verify that stub classes expose .model attribute to prevent AttributeError."""

    def test_stub_classes_have_model_attribute(self):
        """Stub classes must expose a .model attribute whose value is None."""
        # Simulate torch unavailable → stub mode
        with patch("backend.ai_models._try_import", return_value={}):
            # Force re-init of module-level state
            import backend.ai_models as am
            am._registry = {}
            am._STUB_MODE = True
            am._stub_cache.clear()

            # Access any AI model name to trigger stub creation
            stub = am.GATSignalGenerator
            assert stub is not None, "Stub should be created for GATSignalGenerator"

            # The stub class should have .model attribute
            assert hasattr(stub, "model"), "Stub class MUST have .model attribute"
            assert stub.model is None, "Stub .model should be None"

            # Also test instantiation
            instance = stub()
            assert instance.model is None, "Stub instance .model should be None"

    def test_getattr_safe_access_on_stub(self):
        """getattr(gat_network, 'model', None) must not raise in stub mode."""
        with patch("backend.ai_models._try_import", return_value={}):
            import backend.ai_models as am
            am._registry = {}
            am._STUB_MODE = True
            am._stub_cache.clear()

            gat_network_stub = am.gat_network
            # This is the exact pattern used in strategy.py line 160
            result = getattr(gat_network_stub, "model", None)
            assert result is None, "getattr with default should return None, not raise"

    def test_stub_get_cross_stock_signal_returns_dict(self):
        """Stub get_cross_stock_signal should return an empty dict (safe to .get())."""
        with patch("backend.ai_models._try_import", return_value={}):
            import backend.ai_models as am
            am._registry = {}
            am._STUB_MODE = True
            am._stub_cache.clear()

            gat_network_stub = am.gat_network
            result = gat_network_stub.get_cross_stock_signal("AAPL", ["AAPL"], {})
            assert isinstance(result, dict), "Stub get_cross_stock_signal must return dict"
            assert result.get("strength", 0) == 0

    def test_stub_predict_signal_returns_dict(self):
        """Stub predict_signal should return an empty dict."""
        with patch("backend.ai_models._try_import", return_value={}):
            import backend.ai_models as am
            am._registry = {}
            am._STUB_MODE = True
            am._stub_cache.clear()

            rl_stub = am.TradingRLAgent()
            result = rl_stub.predict_signal()
            assert isinstance(result, dict)


# ── Issue 2: fuse_signals KeyError Defense ────────────────────


class TestFuseSignalsDefense:
    """Verify that strategy.py gracefully handles abnormal fuse_signals output."""

    @pytest.fixture
    def mock_strategy_deps(self):
        """Build a TradingStrategy with all mocked dependencies."""
        from backend.trading_engine.strategy import TradingStrategy
        from backend.trading_engine.executor import PaperExecutor
        from backend.trading_engine.portfolio import PortfolioManager
        from backend.trading_engine.risk_manager import RiskManager
        from configs.settings import settings

        transformer = MagicMock()
        transformer.is_ready.return_value = False

        rl_agent = MagicMock()
        rl_agent.is_ready.return_value = False

        sentiment = MagicMock()
        sentiment.get_signal.return_value = {"signal": "neutral", "strength": 0.0, "confidence": 0.0}

        ensemble = MagicMock()

        portfolio = PortfolioManager(settings.TRADING_INITIAL_CAPITAL)
        risk = RiskManager()
        executor = PaperExecutor(portfolio, risk)

        strategy = TradingStrategy(transformer, rl_agent, sentiment, ensemble, executor)
        return strategy, ensemble, sentiment

    def test_fuse_signals_returns_none(self, mock_strategy_deps):
        """When fuse_signals returns None, degrade gracefully to hold."""
        strategy, ensemble, _ = mock_strategy_deps
        ensemble.fuse_signals.return_value = None

        # Build minimal features
        features = np.random.randn(60, 5)
        data_dict = {"AAPL": {"features": features}}
        prices = {"AAPL": 150.0}
        tickers = ["AAPL"]
        features_dict = {"AAPL": features}

        # Should NOT raise KeyError or AttributeError
        result = strategy._analyze_single_ticker("AAPL", data_dict, prices, tickers, features_dict)

        assert result is not None, "Should return a valid dict, not None"
        assert result["decision"] == "hold"
        assert result["strength"] == 0.0
        assert result["confidence"] == 0.0
        assert result["position_size"] == 0.0
        assert result["ensemble_score"] == 0.0
        assert isinstance(result["details"], dict)

    def test_fuse_signals_returns_empty_dict(self, mock_strategy_deps):
        """When fuse_signals returns an empty dict, return the default hold."""
        strategy, ensemble, _ = mock_strategy_deps
        ensemble.fuse_signals.return_value = {}

        features = np.random.randn(60, 5)
        data_dict = {"AAPL": {"features": features}}
        prices = {"AAPL": 150.0}
        tickers = ["AAPL"]
        features_dict = {"AAPL": features}

        result = strategy._analyze_single_ticker("AAPL", data_dict, prices, tickers, features_dict)

        assert result["decision"] == "hold"
        assert result["strength"] == 0.0
        assert result["confidence"] == 0.0

    def test_fuse_signals_returns_partial_dict(self, mock_strategy_deps):
        """When fuse_signals returns a partial dict, fill missing keys with defaults."""
        strategy, ensemble, _ = mock_strategy_deps
        ensemble.fuse_signals.return_value = {"decision": "buy", "strength": 0.8}

        features = np.random.randn(60, 5)
        data_dict = {"AAPL": {"features": features}}
        prices = {"AAPL": 150.0}
        tickers = ["AAPL"]
        features_dict = {"AAPL": features}

        result = strategy._analyze_single_ticker("AAPL", data_dict, prices, tickers, features_dict)

        # Missing keys should get defaults via .get()
        assert result["decision"] == "buy"
        assert result["strength"] == 0.8
        assert result["confidence"] == 0.0    # default
        assert result["position_size"] == 0.0  # default
        assert result["ensemble_score"] == 0.0  # default

    def test_fuse_signals_returns_non_dict(self, mock_strategy_deps):
        """When fuse_signals returns a non-dict, return the default hold."""
        strategy, ensemble, _ = mock_strategy_deps
        ensemble.fuse_signals.return_value = "invalid_string"

        features = np.random.randn(60, 5)
        data_dict = {"AAPL": {"features": features}}
        prices = {"AAPL": 150.0}
        tickers = ["AAPL"]
        features_dict = {"AAPL": features}

        result = strategy._analyze_single_ticker("AAPL", data_dict, prices, tickers, features_dict)

        assert result["decision"] == "hold"
        assert result["strength"] == 0.0

    def test_fuse_signals_with_empty_list(self, mock_strategy_deps):
        """When fuse_signals returns an empty list, the defensive check should fire."""
        strategy, ensemble, _ = mock_strategy_deps
        ensemble.fuse_signals.return_value = []

        features = np.random.randn(60, 5)
        data_dict = {"AAPL": {"features": features}}
        prices = {"AAPL": 150.0}
        tickers = ["AAPL"]
        features_dict = {"AAPL": features}

        result = strategy._analyze_single_ticker("AAPL", data_dict, prices, tickers, features_dict)

        # Empty list is not a dict → triggers defense
        assert result["decision"] == "hold"

    def test_fuse_signals_returns_full_valid_dict(self, mock_strategy_deps):
        """When fuse_signals returns a complete valid dict, values should pass through."""
        strategy, ensemble, _ = mock_strategy_deps
        ensemble.fuse_signals.return_value = {
            "decision": "sell",
            "strength": 0.95,
            "confidence": 0.88,
            "position_size": 0.15,
            "ensemble_score": 0.72,
            "details": {"rsi": 72, "macd": "bearish"},
        }

        features = np.random.randn(60, 5)
        data_dict = {"AAPL": {"features": features}}
        prices = {"AAPL": 150.0}
        tickers = ["AAPL"]
        features_dict = {"AAPL": features}

        result = strategy._analyze_single_ticker("AAPL", data_dict, prices, tickers, features_dict)

        assert result["decision"] == "sell"
        assert result["strength"] == 0.95
        assert result["confidence"] == 0.88
        assert result["position_size"] == 0.15
        assert result["ensemble_score"] == 0.72
        assert result["details"] == {"rsi": 72, "macd": "bearish"}


# ── Issue 2b: Executor KeyError Defense ───────────────────────


class TestExecutorSignalAccess:
    """Verify executor.py uses .get() with defaults for signal fields."""

    def test_execute_signal_batch_with_missing_keys(self):
        """execute_signal_batch should degrade safely when decision/strength/confidence keys are missing."""
        from backend.trading_engine.executor import PaperExecutor
        from backend.trading_engine.portfolio import PortfolioManager
        from backend.trading_engine.risk_manager import RiskManager
        from configs.settings import settings

        portfolio = PortfolioManager(settings.TRADING_INITIAL_CAPITAL)
        risk = RiskManager()
        executor = PaperExecutor(portfolio, risk)

        # signal dict with MISSING keys
        signals = {
            "AAPL": {},  # completely empty
            "MSFT": {"decision": "buy"},  # missing strength, confidence
            "TSLA": {"strength": 0.5},  # missing decision
        }
        prices = {"AAPL": 150.0, "MSFT": 300.0, "TSLA": 200.0}

        # Should NOT raise KeyError
        trades = executor.execute_signal_batch(signals, prices)

        # Default behavior: missing decision → "hold" → returns None for that ticker
        assert isinstance(trades, list)

        # "MSFT" has decision="buy" but no strength → .get("strength", 0.0) = 0.0
        # With strength 0.0, the trade will likely fail size checks and return None
        # The key point is: no KeyError

    def test_execute_signal_batch_with_none_values(self):
        """execute_signal_batch should degrade safely when field values are None."""
        from backend.trading_engine.executor import PaperExecutor
        from backend.trading_engine.portfolio import PortfolioManager
        from backend.trading_engine.risk_manager import RiskManager
        from configs.settings import settings

        portfolio = PortfolioManager(settings.TRADING_INITIAL_CAPITAL)
        risk = RiskManager()
        executor = PaperExecutor(portfolio, risk)

        signals = {
            "AAPL": {"decision": None, "strength": None, "confidence": None},
        }
        prices = {"AAPL": 150.0}

        # Should NOT raise TypeError or KeyError
        trades = executor.execute_signal_batch(signals, prices)

        # None decision → .get("decision", "hold") returns None (not "hold"!)
        # None != "hold" but should be handled gracefully by execute_signal
        assert isinstance(trades, list)


# ── Issue 3: Token & Script Verification ──────────────────────


class TestPushScriptTokenRemoval:
    """Verify no hardcoded tokens exist in push scripts."""

    TOKEN_PATTERNS = ["ghp_", "github_pat_", "GH_TOKEN", "GITHUB_TOKEN"]

    @pytest.mark.parametrize("script_file", [
        "do_push.bat",
        "tmp_push.bat",
        "git_push.sh",
    ])
    def test_no_hardcoded_token(self, script_file):
        """Verify the script contains no hardcoded token."""
        import re
        proj_root = os.path.join(os.path.dirname(__file__), "..")
        filepath = os.path.join(proj_root, script_file)

        if not os.path.exists(filepath):
            pytest.skip(f"{script_file} not found")

        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        for pattern in self.TOKEN_PATTERNS:
            assert pattern not in content, (
                f"{script_file} contains hardcoded token pattern: {pattern}"
            )

        # Also check for raw URL-embedded tokens like https://TOKEN@github.com
        assert not re.search(r"https://[^@\s]+@github\.com", content), (
            f"{script_file} contains URL-embedded credentials"
        )

    def test_git_push_bat_no_token(self):
        """Verify git_push.bat contains no hardcoded token (legacy script, still checked)."""
        import re
        proj_root = os.path.join(os.path.dirname(__file__), "..")
        filepath = os.path.join(proj_root, "git_push.bat")

        if not os.path.exists(filepath):
            pytest.skip("git_push.bat not found")

        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        for pattern in self.TOKEN_PATTERNS:
            assert pattern not in content, f"git_push.bat contains token pattern: {pattern}"


class TestDaemonForeverBatSyntax:
    """Verify daemon_forever.bat batch syntax correctness."""

    def test_file_exists(self):
        """daemon_forever.bat must exist."""
        proj_root = os.path.join(os.path.dirname(__file__), "..")
        filepath = os.path.join(proj_root, "daemon_forever.bat")
        assert os.path.exists(filepath), "daemon_forever.bat must exist"

    def test_no_unmatched_labels(self):
        """Verify all goto target labels exist."""
        proj_root = os.path.join(os.path.dirname(__file__), "..")
        filepath = os.path.join(proj_root, "daemon_forever.bat")
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
            lines = content.splitlines()

        # Collect goto/jump targets (words after :label)
        # :eof is built-in in batch (CMD), no explicit definition needed
        BUILTIN_LABELS = {"eof"}
        labels = set()
        goto_targets = set()
        for line in lines:
            stripped = line.strip()
            # Labels start with : (not :: which is comment)
            if stripped.startswith(":") and not stripped.startswith("::"):
                labels.add(stripped.split()[0].lstrip(":"))

            # goto targets / call targets (normalize: strip leading colon)
            if "goto " in stripped.lower():
                parts = stripped.lower().split("goto ")
                if len(parts) > 1:
                    target = parts[1].strip().split()[0].strip().lstrip(":")
                    goto_targets.add(target)
            if "call :" in stripped.lower():
                parts = stripped.lower().split("call :")
                if len(parts) > 1:
                    target = parts[1].strip().split()[0].strip().lstrip(":")
                    goto_targets.add(target)

        for target in goto_targets:
            if target in BUILTIN_LABELS:
                continue
            assert target in labels, (
                f"goto/call target ':{target}' not defined as label"
            )

    def test_variables_defined_before_use(self):
        """Verify key environment variables are defined before use."""
        proj_root = os.path.join(os.path.dirname(__file__), "..")
        filepath = os.path.join(proj_root, "daemon_forever.bat")
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        required_vars = ["GIT_PUSH_EVERY", "PUSH_COUNTER", "PROJ", "PY"]
        for var in required_vars:
            # Variables may use various syntaxes:
            #   set VAR=val, set "VAR=val", set /a VAR=val, set /a "VAR"=val
            found = (
                f"set {var}=" in content
                or f"set \"{var}=" in content      # set "VAR=val"
                or f"set \"{var}\"=" in content
                or f"set /a {var}=" in content
                or f"set /a \"{var}\"=" in content
            )
            assert found, (
                f"Required variable {var} not set in daemon_forever.bat"
            )

    def test_paren_balancing(self):
        """Check that parentheses are roughly balanced."""
        proj_root = os.path.join(os.path.dirname(__file__), "..")
        filepath = os.path.join(proj_root, "daemon_forever.bat")
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        open_parens = content.count("(")
        close_parens = content.count(")")
        # Not perfect (some in echo strings) but a rough check
        diff = abs(open_parens - close_parens)
        assert diff <= 15, (
            f"Parentheses imbalance: {open_parens} open vs {close_parens} close"
        )


# ── Issue 4: Tiger sync_all_to_db ─────────────────────────────


class TestTigerSyncAllToDb:
    """Verify sync_all_to_db method exists and degrades gracefully."""

    def test_sync_all_to_db_method_exists(self):
        """sync_all_to_db must exist on TigerClient."""
        from backend.data_engine.tiger_client import TigerClient
        assert hasattr(TigerClient, "sync_all_to_db"), (
            "TigerClient must have sync_all_to_db method"
        )

    def test_sync_all_to_db_not_connected(self):
        """sync_all_to_db returns a not_connected error when disconnected."""
        from backend.data_engine.tiger_client import TigerClient
        client = TigerClient()
        client._connected = False

        result = client.sync_all_to_db()
        assert isinstance(result, dict)
        assert result["synced"] is False
        assert result["error"] == "not_connected"

    def test_sync_all_to_db_returns_dict_on_failure(self):
        """On exception, sync_all_to_db should safely return a dict with error and not raise."""
        from backend.data_engine.tiger_client import TigerClient
        client = TigerClient()
        client._connected = True

        # HistoricalStore is imported inside sync_all_to_db, so we patch at the
        # import location: backend.data_engine.historical_store.HistoricalStore
        with patch("backend.data_engine.historical_store.HistoricalStore", side_effect=ImportError("test")):
            result = client.sync_all_to_db()
            assert isinstance(result, dict)
            assert result["synced"] is False

    @pytest.mark.skip(reason="auto_trader.py archived, replaced by trading_pipeline.py in v2.2")
    def test_auto_trader_calls_sync_all_to_db(self):
        """Verify auto_trader.py calls tiger_client.sync_all_to_db() in run_cycle."""
        proj_root = os.path.join(os.path.dirname(__file__), "..")
        filepath = os.path.join(proj_root, "auto_trader.py")

        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        assert "tiger_client.sync_all_to_db()" in content, (
            "auto_trader.py must call tiger_client.sync_all_to_db()"
        )
        assert "sync_all_to_db" in content


# ── Integration: End-to-End Stub Mode ─────────────────────────


class TestStubModeEndToEnd:
    """End-to-end verification that stub mode works without crashes."""

    def test_ai_models_import_without_torch(self):
        """import backend.ai_models must not raise even if torch is unavailable."""
        # The module itself should import without torch
        import backend.ai_models as am
        assert am._STUB_MODE is True or am._STUB_MODE is False
        # If stub mode, verify classes are accessible
        if am._STUB_MODE:
            assert am.GATSignalGenerator is not None
            assert am.TransformerPredictor is not None
            assert am.TradingRLAgent is not None
            assert am.gat_network is not None

    def test_all_stub_classes_have_required_attrs(self):
        """All stub classes should expose a consistent public API."""
        import backend.ai_models as am

        # Force stub mode
        original_registry = am._registry
        original_stub_mode = am._STUB_MODE
        try:
            am._registry = {}
            am._STUB_MODE = True
            am._stub_cache.clear()

            required_stub_classes = [
                "GATSignalGenerator",
                "TransformerPredictor",
                "TradingRLAgent",
                "SentimentAnalyzer",
                "SignalEnsemble",
                "CrossStockCorrelation",
                "cross_stock",
                "gat_network",
                "StockGAT",
            ]

            for cls_name in required_stub_classes:
                stub = getattr(am, cls_name)
                # Stub should be a class (type)
                assert isinstance(stub, type) or callable(stub), (
                    f"{cls_name} should be a class or callable"
                )
                # Should have model attribute (for GAT fix)
                assert hasattr(stub, "model"), (
                    f"{cls_name} must have .model attribute"
                )
        finally:
            am._registry = original_registry
            am._stub_mode = original_stub_mode


# ── Strategy Regression: Cross-Stock Signal Handling ──────────


class TestCrossStockSignalDefense:
    """Verify cross-stock signal access pattern works in both stub and real mode."""

    def test_getattr_gat_network_model_pattern(self):
        """Verify the strategy getattr(gat_network, 'model', None) pattern is safe in stub mode."""
        import backend.ai_models as am
        original_registry = am._registry
        original_stub_mode = am._STUB_MODE
        try:
            am._registry = {}
            am._STUB_MODE = True
            am._stub_cache.clear()

            gat = am.gat_network
            # Exact pattern from strategy.py:160
            model = getattr(gat, 'model', None)
            assert model is None

            # get_cross_stock_signal should work
            result = gat.get_cross_stock_signal("AAPL", ["AAPL", "MSFT"], {})
            assert isinstance(result, dict)
            assert result.get("strength", 0) == 0
        finally:
            am._registry = original_registry
            am._stub_mode = original_stub_mode


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
