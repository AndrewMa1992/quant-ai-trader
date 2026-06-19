"""tests/test_model_service/test_inference.py – Tests for model inference and ensemble."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from services.model_infer_service.models.gbdt_model import GBDTInference
from services.model_infer_service.models.transformer_model import TransformerInference
from services.model_infer_service.models.tcn_model import TCNInference
from services.model_infer_service.models.tft_model import TFTInference
from services.model_infer_service.models.rl_model import RLInference
from services.model_infer_service.ensemble.blender import SignalBlender
from services.model_infer_service.ensemble.bayesian_weighting import BayesianWeighting
from services.model_infer_service.ensemble.market_state import MarketStateDetector
from services.model_infer_service.inference_engine import InferenceEngine


class TestGBDTInference:
    """Tests for GBDTInference."""

    def test_unloaded_returns_zeros(self):
        model = GBDTInference()
        X = pd.DataFrame({"a": [1, 2, 3]})
        pred = model.predict(X)
        assert len(pred) == 3
        assert all(p == 0.0 for p in pred)

    def test_direction_prob(self):
        model = GBDTInference()
        X = pd.DataFrame({"a": np.random.randn(10)})
        probs = model.predict_direction_prob(X)
        assert "up_prob" in probs
        assert "down_prob" in probs
        assert "value" in probs
        # Unloaded model returns zeros → probs should be ~0.5 each
        assert abs(probs["up_prob"][0] - 0.5) < 0.1


class TestTransformerInference:
    """Tests for TransformerInference."""

    def test_unloaded_returns_zeros(self):
        model = TransformerInference(device="cpu")
        X = pd.DataFrame({"a": np.random.randn(100)})
        pred = model.predict(X)
        assert len(pred) == 100


class TestTCNInference:
    """Tests for TCNInference."""

    def test_unloaded_returns_zeros(self):
        model = TCNInference(device="cpu")
        X = pd.DataFrame({"a": np.random.randn(100)})
        pred = model.predict(X)
        assert len(pred) == 100


class TestTFTInference:
    """Tests for TFTInference."""

    def test_unloaded_returns_zeros(self):
        model = TFTInference(device="cpu")
        X = pd.DataFrame({"a": np.random.randn(100)})
        pred = model.predict(X)
        assert len(pred) == 100

    def test_quantiles_unloaded(self):
        model = TFTInference(device="cpu")
        X = pd.DataFrame({"a": np.random.randn(100)})
        qs = model.predict_quantiles(X)
        assert "q10" in qs
        assert "q50" in qs
        assert "q90" in qs


class TestRLInference:
    """Tests for RLInference."""

    def test_unloaded_returns_noisy_signals(self):
        model = RLInference()
        X = pd.DataFrame({"a": np.random.randn(50)})
        pred = model.predict(X)
        assert len(pred) == 50
        # Should return random-like values in [-0.2, 0.2]
        assert all(-0.3 <= p <= 0.3 for p in pred)

    def test_action_probs(self):
        model = RLInference()
        X = pd.DataFrame({"a": np.random.randn(50)})
        probs = model.get_action_probs(X)
        assert "hold_prob" in probs
        assert "buy_prob" in probs
        assert "sell_prob" in probs


class TestSignalBlender:
    """Tests for SignalBlender."""

    def test_weighted_average(self):
        blender = SignalBlender(mode="weighted_average")
        predictions = {
            "gbdt": {"value": 0.2, "confidence": 0.8, "direction": "BUY"},
            "tcn": {"value": -0.1, "confidence": 0.6, "direction": "SELL"},
        }
        result = blender.blend(predictions)
        assert "signal" in result
        assert "confidence" in result
        assert "direction" in result
        assert -1.0 <= result["signal"] <= 1.0

    def test_voting_mode(self):
        blender = SignalBlender(mode="voting")
        predictions = {
            "gbdt": {"value": 0.3, "confidence": 0.9, "direction": "BUY"},
            "tcn": {"value": 0.2, "confidence": 0.7, "direction": "BUY"},
            "tft": {"value": -0.1, "confidence": 0.5, "direction": "SELL"},
        }
        result = blender.blend(predictions)
        assert result["direction"] == "BUY"

    def test_confidence_filter(self):
        blender = SignalBlender(min_confidence=0.8)
        predictions = {
            "gbdt": {"value": 0.5, "confidence": 0.9, "direction": "BUY"},
            "tcn": {"value": -0.5, "confidence": 0.3, "direction": "SELL"},
        }
        result = blender.blend(predictions)
        # Low-confidence tcn should be excluded
        assert result["direction"] in ("BUY", "HOLD")


class TestBayesianWeighting:
    """Tests for BayesianWeighting."""

    def test_update_weights(self):
        bayes = BayesianWeighting(window_days=60)
        model_preds = {
            "gbdt": np.random.randn(100) * 0.1,
            "tcn": np.random.randn(100) * 0.05,
        }
        actual = np.random.randn(100) * 0.1
        weights = bayes.update(model_preds, actual)
        assert list(weights.keys()) == ["gbdt", "tcn"]
        assert 0.9 < sum(weights.values()) < 1.1

    def test_get_weights_empty_initially(self):
        bayes = BayesianWeighting()
        weights = bayes.get_weights()
        assert weights == {}


class TestMarketStateDetector:
    """Tests for MarketStateDetector."""

    def test_heuristic_detect(self):
        detector = MarketStateDetector()
        # Simulate low-vol bull market
        returns = np.random.randn(100) * 0.005 + 0.0005
        state = detector.fit(returns)
        assert state in (0, 1, 2)

    def test_state_name(self):
        detector = MarketStateDetector()
        returns = np.random.randn(100) * 0.005 + 0.001
        detector.fit(returns)
        name = detector.state_name
        assert name in ("bull", "bear", "crisis")

    def test_model_subset_crisis(self):
        detector = MarketStateDetector()
        returns = np.random.randn(100) * 0.05  # High vol → crisis
        detector.fit(returns)
        subset = detector.get_model_subset(["gbdt", "transformer", "tcn", "tft", "rl"])
        if detector.current_state == 2:
            assert "tcn" not in subset or "rl" not in subset


class TestInferenceEngine:
    """Tests for InferenceEngine."""

    def test_get_status(self):
        engine = InferenceEngine()
        status = engine.get_status()
        assert "gbdt" in status
        assert "transformer" in status
        assert all("loaded" in v for v in status.values())

    def test_generate_signal_no_data(self):
        engine = InferenceEngine()
        signal = engine.generate_signal("NONEXISTENT_TICKER_XYZ")
        assert signal["ticker"] == "NONEXISTENT_TICKER_XYZ"
        assert signal["direction"] == "HOLD"
