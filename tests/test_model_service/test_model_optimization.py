"""Tests for AI model optimization: scaler, RL zeros, blender renormalize, preprocess."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.preprocessing import StandardScaler


def test_align_features_and_scaler_roundtrip():
    from services.model_infer_service.models.preprocess import align_features, apply_scaler

    names = ["a", "b", "c"]
    X = pd.DataFrame({"a": [1.0, 2.0], "c": [3.0, 4.0]})
    aligned, miss = align_features(X, names)
    assert list(aligned.columns) == names
    assert miss == pytest.approx(1 / 3)
    assert aligned["b"].iloc[0] == 0.0

    scaler = StandardScaler()
    scaler.fit([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]])
    out = apply_scaler(aligned, scaler)
    assert out.shape == (2, 3)
    assert out.dtype == np.float32


def test_confidence_haircut():
    from services.model_infer_service.models.preprocess import confidence_haircut

    assert confidence_haircut(0.8, 0.0) == pytest.approx(0.8)
    assert confidence_haircut(1.0, 0.5) == pytest.approx(0.5)


def test_rl_unloaded_returns_zeros_not_noise():
    from services.model_infer_service.models.rl_model import RLInference

    model = RLInference()
    X = pd.DataFrame({"a": np.random.randn(50)})
    pred = model.predict(X)
    assert len(pred) == 50
    assert np.allclose(pred, 0.0)


def test_blender_renormalizes_weights_after_filter():
    from services.model_infer_service.ensemble.blender import SignalBlender

    blender = SignalBlender(mode="weighted_average", min_confidence=0.5)
    predictions = {
        "gbdt": {"value": 0.4, "confidence": 0.9, "direction": "BUY"},
        "tcn": {"value": -0.4, "confidence": 0.2, "direction": "SELL"},  # filtered out
    }
    # If tcn weight leaked, signal would be pulled toward 0 / negative
    result = blender.blend(predictions, weights={"gbdt": 0.5, "tcn": 0.5})
    assert result["signal"] == pytest.approx(0.4, abs=1e-6)
    assert "gbdt" in result["components"]
    assert "tcn" not in result["components"]


def test_bayesian_weights_update():
    from services.model_infer_service.ensemble.bayesian_weighting import BayesianWeighting

    bw = BayesianWeighting(window_days=30, temperature=2.0)
    rng = np.random.default_rng(0)
    actual = rng.normal(0, 0.01, 40)
    preds = {
        "good": actual + rng.normal(0, 0.002, 40),
        "bad": -actual + rng.normal(0, 0.02, 40),
    }
    weights = bw.update(preds, actual)
    assert abs(sum(weights.values()) - 1.0) < 1e-6
    assert weights["good"] >= weights["bad"]


def test_market_state_subset():
    from services.model_infer_service.ensemble.market_state import MarketStateDetector

    ms = MarketStateDetector()
    returns = np.concatenate([np.full(40, 0.001), np.full(40, -0.002)])
    ms._heuristic_detect(returns)
    available = ["gbdt", "transformer", "tcn", "tft", "rl"]
    subset = ms.get_model_subset(available)
    assert isinstance(subset, list)
    assert all(m in available for m in subset)


def test_transformer_applies_scaler(tmp_path):
    """Save a tiny PatchTST checkpoint with scaler and ensure load+predict works."""
    torch = pytest.importorskip("torch")
    from sklearn.preprocessing import StandardScaler
    from services.model_train_service.trainers.transformer_trainer import PatchTSTRegressor
    from services.model_infer_service.models.transformer_model import TransformerInference

    n_feat, seq_len = 4, 8
    model = PatchTSTRegressor(
        n_features=n_feat, d_model=16, n_heads=2, n_layers=1, dropout=0.0, seq_len=seq_len
    )
    scaler = StandardScaler()
    rng = np.random.default_rng(1)
    raw = rng.normal(size=(120, n_feat))
    scaler.fit(raw)
    path = tmp_path / "transformer_v1.pt"
    torch.save(
        {
            "model_state": model.state_dict(),
            "config": {
                "n_features": n_feat,
                "d_model": 16,
                "n_heads": 2,
                "n_layers": 1,
                "dropout": 0.0,
                "seq_len": seq_len,
            },
            "feature_names": [f"f{i}" for i in range(n_feat)],
            "scaler": scaler,
        },
        path,
    )

    infer = TransformerInference(device="cpu")
    assert infer.load(str(path)) is True
    assert infer._scaler is not None
    X = pd.DataFrame(raw, columns=[f"f{i}" for i in range(n_feat)])
    pred = infer.predict(X)
    assert len(pred) == len(X)
    assert np.isfinite(pred).all()


def test_rl_obs_builder_shape():
    from services.model_infer_service.models.rl_model import RLInference

    rl = RLInference()
    rl._window = 5
    rl._feature_names = ["ret_1d", "f1", "f2"]
    X = pd.DataFrame(
        {
            "ret_1d": np.linspace(-0.01, 0.01, 20),
            "f1": np.random.randn(20),
            "f2": np.random.randn(20),
        }
    )
    data = rl._build_env_data(X)
    # [ret, features...] → 1 + 3 = 4 cols
    assert data.shape == (20, 4)
    obs = rl._obs_from_window(data, end=10, position=0.0)
    assert obs.shape == (5, 5)  # window × (data_cols + position)
