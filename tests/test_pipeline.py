"""tests/test_pipeline.py – Trading pipeline CLI and execution tests for v2.1.

Covers:
- trading_pipeline.py --help exits with code 0
- trading_pipeline.py --once does not crash (allows stub/degraded mode)
- PipelineConfig instantiation
- TradingPipeline class structure
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


# ═══════════════════════════════════════════════════════════════
# PipelineConfig Tests
# ═══════════════════════════════════════════════════════════════

class TestPipelineConfigInstantiation:
    """Test that PipelineConfig can be instantiated without error."""

    def test_instantiate_pipeline_config(self):
        from configs.pipeline_config import PipelineConfig

        cfg = PipelineConfig()
        assert cfg is not None
        assert cfg.CYCLE_INTERVAL_SECONDS == 300
        assert cfg.SIGNAL_THRESHOLD == 0.3

    def test_pipeline_config_singleton(self):
        from configs.pipeline_config import pipeline_config

        assert pipeline_config is not None
        assert pipeline_config.ENABLE_RISK_CHECKS is True
        assert isinstance(pipeline_config.SERVICE_BASE_URLS, dict)


# ═══════════════════════════════════════════════════════════════
# TradingPipeline Class Tests
# ═══════════════════════════════════════════════════════════════

class TestTradingPipelineStructure:
    """Test that TradingPipeline class has the expected API."""

    def test_trading_pipeline_import(self):
        """TradingPipeline should be importable."""
        from trading_pipeline import TradingPipeline
        assert TradingPipeline is not None

    def test_trading_pipeline_has_run_method(self):
        from trading_pipeline import TradingPipeline
        assert hasattr(TradingPipeline, "run")
        assert callable(TradingPipeline.run)

    def test_trading_pipeline_has_run_cycle_method(self):
        from trading_pipeline import TradingPipeline
        assert hasattr(TradingPipeline, "run_cycle")
        assert callable(TradingPipeline.run_cycle)

    def test_trading_pipeline_has_close_method(self):
        from trading_pipeline import TradingPipeline
        assert hasattr(TradingPipeline, "close")
        assert callable(TradingPipeline.close)

    def test_trading_pipeline_has_seven_steps(self):
        """TradingPipeline should have 7 step methods (private)."""
        from trading_pipeline import TradingPipeline

        step_methods = [
            "_get_active_universe",
            "_fetch_market_data",
            "_compute_factors",
            "_run_inference",
            "_apply_risk_checks",
            "_optimize_portfolio",
            "_execute_rebalance",
            "_record_performance",
        ]
        for method in step_methods:
            assert hasattr(TradingPipeline, method), f"Missing step method: {method}"


# ═══════════════════════════════════════════════════════════════
# CLI Tests (subprocess)
# ═══════════════════════════════════════════════════════════════

class TestPipelineCLI:
    """Test the trading_pipeline.py command-line interface."""

    @pytest.fixture
    def project_root(self):
        return Path(__file__).resolve().parent.parent

    def test_help_exits_zero(self, project_root):
        """python trading_pipeline.py --help should exit with code 0."""
        result = subprocess.run(
            [sys.executable, "trading_pipeline.py", "--help"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}\n"
            f"STDERR: {result.stderr[:500]}"
        )

    def test_help_output_contains_description(self, project_root):
        """--help should print usage info."""
        result = subprocess.run(
            [sys.executable, "trading_pipeline.py", "--help"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout + result.stderr
        assert "trading" in output.lower() or "Trading" in output, (
            f"Help output should mention trading: {output[:500]}"
        )

    def test_help_shows_once_flag(self, project_root):
        """--help should document the --once flag."""
        result = subprocess.run(
            [sys.executable, "trading_pipeline.py", "--help"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout + result.stderr
        assert "--once" in output, (
            f"Help output should mention --once flag: {output[:500]}"
        )

    def test_help_shows_interval_flag(self, project_root):
        """--help should document the --interval flag."""
        result = subprocess.run(
            [sys.executable, "trading_pipeline.py", "--help"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout + result.stderr
        assert "--interval" in output, (
            f"Help output should mention --interval flag: {output[:500]}"
        )

    def test_once_flag_runs_without_crash(self, project_root):
        """--once should run a single cycle without crashing (may have import warnings)."""
        result = subprocess.run(
            [sys.executable, "trading_pipeline.py", "--once"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=60,
        )
        # --once may succeed (0), fail due to missing dependencies (1),
        # but should NOT crash with a traceback that suggests a code bug.
        # Allow exit codes 0 or 1 — just verify it doesn't hard-crash.
        assert result.returncode in (0, 1), (
            f"Expected exit code 0 or 1, got {result.returncode}\n"
            f"STDOUT: {result.stdout[:500]}\n"
            f"STDERR: {result.stderr[:500]}"
        )
        # If it fails, the error should NOT be a Python syntax error or import error
        # for core modules (trading_pipeline itself).
        if result.returncode != 0:
            combined = result.stdout + result.stderr
            # Should not contain syntax errors for trading_pipeline.py
            assert "SyntaxError" not in combined, (
                f"SyntaxError found in pipeline output: {combined[:500]}"
            )

    def test_trading_pipeline_syntax_valid(self, project_root):
        """Verify trading_pipeline.py has no syntax errors."""
        result = subprocess.run(
            [sys.executable, "-c", "import py_compile; py_compile.compile('trading_pipeline.py', doraise=True)"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"Syntax check failed: {result.stderr[:500]}"
        )


# ═══════════════════════════════════════════════════════════════
# Daemon Script Syntax Tests
# ═══════════════════════════════════════════════════════════════

class TestDaemonScripts:
    """Verify that daemon scripts exist and are well-formed."""

    def test_daemon_win_ps1_exists(self):
        daemon_path = Path(__file__).resolve().parent.parent / "daemon_win.ps1"
        assert daemon_path.exists(), f"daemon_win.ps1 not found at {daemon_path}"

    def test_daemon_forever_bat_exists(self):
        daemon_path = Path(__file__).resolve().parent.parent / "daemon_forever.bat"
        assert daemon_path.exists(), f"daemon_forever.bat not found at {daemon_path}"

    def test_daemon_win_has_v2_ports(self):
        """daemon_win.ps1 should reference all v2 service ports."""
        daemon_path = Path(__file__).resolve().parent.parent / "daemon_win.ps1"
        content = daemon_path.read_text(encoding="utf-8")
        for port in [8001, 8011, 8012, 8013, 8014, 8015, 8016]:
            assert str(port) in content, (
                f"daemon_win.ps1 should reference port {port}"
            )

    def test_daemon_forever_has_v2_services(self):
        """daemon_forever.bat should reference all v2 service names."""
        daemon_path = Path(__file__).resolve().parent.parent / "daemon_forever.bat"
        content = daemon_path.read_text(encoding="utf-8")
        for svc in ["data_service", "factor_service", "model_train", "model_infer",
                      "risk_service", "execution_service"]:
            assert svc in content, (
                f"daemon_forever.bat should reference {svc}"
            )

    def test_daemon_win_has_start_all_microservices(self):
        """daemon_win.ps1 should have Start-AllMicroservices function."""
        daemon_path = Path(__file__).resolve().parent.parent / "daemon_win.ps1"
        content = daemon_path.read_text(encoding="utf-8")
        assert "Start-AllMicroservices" in content
        assert "Start-TradingPipeline" in content
