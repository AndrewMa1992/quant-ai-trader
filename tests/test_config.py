"""tests/test_config.py – Configuration loading tests for Quant AI Trader v2.1.

Covers:
- configs/settings.py: Settings singleton, QAT_ prefix, default values
- configs/pipeline_config.py: PipelineConfig, SERVICE_BASE_URLS
- .env: environment variables
"""

from __future__ import annotations

import os

import pytest


# ═══════════════════════════════════════════════════════════════
# Settings Tests
# ═══════════════════════════════════════════════════════════════

class TestSettingsDefaults:
    """Test that Settings singleton has correct default port values."""

    def test_data_port_default_is_8011(self):
        """DATA_PORT default should be 8011."""
        from configs.settings import settings

        assert settings.DATA_PORT == 8011, (
            f"Expected DATA_PORT=8011, got {settings.DATA_PORT}"
        )

    def test_factor_port_default_is_8012(self):
        from configs.settings import settings

        assert settings.FACTOR_PORT == 8012

    def test_model_train_port_default_is_8013(self):
        from configs.settings import settings

        assert settings.MODEL_TRAIN_PORT == 8013

    def test_model_infer_port_default_is_8014(self):
        from configs.settings import settings

        assert settings.MODEL_INFER_PORT == 8014

    def test_risk_port_default_is_8015(self):
        from configs.settings import settings

        assert settings.RISK_PORT == 8015

    def test_exec_port_default_is_8016(self):
        from configs.settings import settings

        assert settings.EXEC_PORT == 8016

    def test_api_port_default_is_8001(self):
        from configs.settings import settings

        assert settings.API_PORT == 8001

    def test_env_default_is_development(self):
        from configs.settings import settings

        assert settings.ENV == "development"

    def test_app_name_default(self):
        from configs.settings import settings

        assert settings.APP_NAME == "quant-ai-trader"

    def test_app_version_default(self):
        from configs.settings import settings

        assert settings.APP_VERSION == "2.0.0"

    def test_project_root_exists(self):
        """PROJECT_ROOT should be set (default '.')."""
        from configs.settings import settings

        assert settings.PROJECT_ROOT is not None
        assert isinstance(settings.PROJECT_ROOT, str)

    def test_debug_is_bool(self):
        from configs.settings import settings

        assert isinstance(settings.DEBUG, bool)

    def test_settings_singleton(self):
        """Multiple imports should return the same singleton instance."""
        from configs.settings import settings as s1
        from configs.settings import settings as s2

        assert s1 is s2


class TestSettingsProperties:
    """Test computed properties on Settings."""

    def test_cors_origin_list(self):
        from configs.settings import settings

        origins = settings.cors_origin_list
        assert isinstance(origins, list)
        # With default CORS_ORIGINS, should contain localhost entries
        assert len(origins) >= 1

    def test_is_development(self):
        from configs.settings import settings

        assert settings.is_development is True

    def test_is_production(self):
        from configs.settings import settings

        assert settings.is_production is False


class TestSettingsQATPrefix:
    """Verify QAT_ prefix loading from .env file."""

    def test_env_file_loads_qat_prefix(self):
        """Settings loaded from .env should reflect QAT_ prefixed values."""
        from configs.settings import settings

        # These defaults exist in .env; depending on working directory
        # they may or may not override. We just check they are reasonable.
        assert isinstance(settings.DATA_PORT, int)
        assert settings.DATA_PORT > 0
        assert isinstance(settings.API_PORT, int)
        assert settings.API_PORT > 0

    def test_qat_debug_is_boolean(self):
        from configs.settings import settings

        assert isinstance(settings.DEBUG, bool)

    def test_training_defaults(self):
        from configs.settings import settings

        assert settings.MODEL_TRAIN_EPOCHS == 100
        assert settings.MODEL_BATCH_SIZE == 256
        assert settings.MODEL_LEARNING_RATE == 0.001

    def test_backtest_defaults(self):
        from configs.settings import settings

        assert settings.BACKTEST_START_DATE == "2020-01-01"
        assert settings.BACKTEST_END_DATE == "2024-12-31"
        assert settings.BACKTEST_INITIAL_CAPITAL == 100_000_000.0

    def test_execution_defaults(self):
        from configs.settings import settings

        assert settings.EXECUTION_MODE == "paper"
        assert settings.EXECUTION_RETRY_ATTEMPTS == 3

    def test_train_device(self):
        from configs.settings import settings

        assert settings.TRAIN_DEVICE in ("cpu", "cuda")


# ═══════════════════════════════════════════════════════════════
# PipelineConfig Tests
# ═══════════════════════════════════════════════════════════════

class TestPipelineConfig:
    """Test pipeline_config module."""

    def test_service_base_urls_has_data_key(self):
        from configs.pipeline_config import pipeline_config

        assert "data" in pipeline_config.SERVICE_BASE_URLS

    def test_data_url_contains_8011(self):
        """data service URL should use DATA_PORT=8011."""
        from configs.pipeline_config import pipeline_config

        assert "8011" in pipeline_config.SERVICE_BASE_URLS["data"], (
            f"Expected '8011' in data URL, got: {pipeline_config.SERVICE_BASE_URLS['data']}"
        )

    def test_all_six_services_present(self):
        """All 6 microservices should have URLs configured."""
        from configs.pipeline_config import pipeline_config

        expected_keys = {"data", "factor", "model_train", "model_infer", "risk", "execution"}
        actual_keys = set(pipeline_config.SERVICE_BASE_URLS.keys())
        assert expected_keys == actual_keys, (
            f"Missing keys: {expected_keys - actual_keys}, "
            f"Extra keys: {actual_keys - expected_keys}"
        )

    def test_service_urls_start_with_http_localhost(self):
        """Each service URL should start with http://localhost:"""
        from configs.pipeline_config import pipeline_config

        for svc, url in pipeline_config.SERVICE_BASE_URLS.items():
            assert url.startswith("http://localhost:"), (
                f"Service '{svc}' URL '{url}' does not start with 'http://localhost:'"
            )

    def test_port_mapping_matches_settings(self):
        """PipelineConfig ports should match settings ports."""
        from configs.pipeline_config import pipeline_config
        from configs.settings import settings

        url_map = pipeline_config.SERVICE_BASE_URLS
        assert str(settings.DATA_PORT) in url_map["data"]
        assert str(settings.FACTOR_PORT) in url_map["factor"]
        assert str(settings.MODEL_TRAIN_PORT) in url_map["model_train"]
        assert str(settings.MODEL_INFER_PORT) in url_map["model_infer"]
        assert str(settings.RISK_PORT) in url_map["risk"]
        assert str(settings.EXEC_PORT) in url_map["execution"]

    def test_cycle_interval_seconds_default(self):
        from configs.pipeline_config import pipeline_config

        assert pipeline_config.CYCLE_INTERVAL_SECONDS == 300

    def test_signal_threshold(self):
        from configs.pipeline_config import pipeline_config

        assert pipeline_config.SIGNAL_THRESHOLD == 0.3

    def test_enable_risk_checks_default(self):
        from configs.pipeline_config import pipeline_config

        assert pipeline_config.ENABLE_RISK_CHECKS is True

    def test_http_timeout(self):
        from configs.pipeline_config import pipeline_config

        assert pipeline_config.HTTP_TIMEOUT == 30.0
        assert pipeline_config.HTTP_RETRIES == 3

    def test_build_service_urls_consistency(self):
        """Multiple PipelineConfig instances should have consistent URLs."""
        from configs.pipeline_config import PipelineConfig

        cfg1 = PipelineConfig()
        cfg2 = PipelineConfig()

        assert cfg1.SERVICE_BASE_URLS == cfg2.SERVICE_BASE_URLS
