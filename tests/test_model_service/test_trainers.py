"""tests/test_model_service/test_trainers.py – Tests for all model trainers."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from services.model_train_service.trainers.gbdt_trainer import GBDTTrainer
from services.model_train_service.trainers.trainer_base import TrainerBase


class TestGBDTTrainer:
    """Tests for GBDTTrainer."""

    @pytest.fixture
    def trainer(self) -> GBDTTrainer:
        return GBDTTrainer(gbdt_type="lightgbm")

    @pytest.fixture
    def data(self) -> tuple[pd.DataFrame, pd.Series]:
        np.random.seed(42)
        n = 500
        X = pd.DataFrame({
            f"feature_{i}": np.random.randn(n) for i in range(5)
        })
        y = pd.Series(np.random.randn(n) * 0.1)
        return X, y

    def test_fit_returns_metrics(self, trainer: GBDTTrainer, data: tuple[pd.DataFrame, pd.Series]):
        X, y = data
        metrics = trainer.fit(X, y)
        assert "val_rmse" in metrics or "val_loss" in metrics
        assert isinstance(metrics, dict)

    def test_predict_shape(self, trainer: GBDTTrainer, data: tuple[pd.DataFrame, pd.Series]):
        X, y = data
        trainer.fit(X, y)
        pred = trainer.predict(X.head(10))
        assert len(pred) == 10

    def test_get_feature_importance(self, trainer: GBDTTrainer, data: tuple[pd.DataFrame, pd.Series]):
        X, y = data
        trainer.fit(X, y)
        imp = trainer.get_feature_importance()
        assert isinstance(imp, pd.Series)

    def test_save_and_load(self, trainer: GBDTTrainer, data: tuple[pd.DataFrame, pd.Series], tmp_path):
        X, y = data
        trainer.fit(X, y)
        path = str(tmp_path / "test_gbdt.pkl")
        trainer.save(path)

        trainer2 = GBDTTrainer()
        trainer2.load(path)
        assert trainer2.loaded
        pred = trainer2.predict(X.head(5))
        assert len(pred) == 5

    def test_fallback_on_missing_lib(self):
        """Test that sklearn fallback works when specialized libs are absent."""
        # GBDTTrainer always works because of sklearn fallback
        X = pd.DataFrame({"a": [1, 2, 3, 4, 5]}, dtype=float)
        y = pd.Series([0.1, 0.2, 0.1, 0.3, 0.2])

        trainer = GBDTTrainer(gbdt_type="lightgbm")
        # This should trigger sklearn fallback if lightgbm not installed
        metrics = trainer.fit(X, y)
        assert "val_rmse" in metrics


class TestTransformerTrainer:
    """Tests for TransformerTrainer (lightweight)."""

    @pytest.fixture
    def data(self) -> tuple[pd.DataFrame, pd.Series]:
        np.random.seed(42)
        n = 200
        X = pd.DataFrame({
            f"f{i}": np.random.randn(n).cumsum() * 0.1 for i in range(4)
        })
        y = pd.Series(np.random.randn(n) * 0.01)
        return X, y

    def test_init_cpu_d_model(self):
        from services.model_train_service.trainers.transformer_trainer import TransformerTrainer
        trainer = TransformerTrainer(device="cpu")
        assert trainer.d_model == 128
        assert trainer.n_layers == 4

    def test_init_gpu_d_model(self):
        from services.model_train_service.trainers.transformer_trainer import TransformerTrainer
        trainer = TransformerTrainer(device="cuda")
        assert trainer.d_model == 512

    def test_fit_returns_metrics(self, data: tuple[pd.DataFrame, pd.Series]):
        from services.model_train_service.trainers.transformer_trainer import TransformerTrainer
        X, y = data
        trainer = TransformerTrainer(device="cpu", d_model=32, n_heads=4, n_layers=2, seq_len=16)
        metrics = trainer.fit(X, y, epochs=3, batch_size=32)
        assert "val_loss" in metrics

    def test_predict_shape(self, data: tuple[pd.DataFrame, pd.Series]):
        from services.model_train_service.trainers.transformer_trainer import TransformerTrainer
        X, y = data
        trainer = TransformerTrainer(device="cpu", d_model=32, n_heads=4, n_layers=2, seq_len=16)
        trainer.fit(X, y, epochs=3, batch_size=32)
        pred = trainer.predict(X)
        assert len(pred) == len(X)


class TestTCNTrainer:
    """Tests for TCNTrainer."""

    @pytest.fixture
    def data(self) -> tuple[pd.DataFrame, pd.Series]:
        np.random.seed(42)
        n = 200
        X = pd.DataFrame({f"f{i}": np.random.randn(n) for i in range(4)})
        y = pd.Series(np.random.randn(n) * 0.01)
        return X, y

    def test_fit_returns_metrics(self, data: tuple[pd.DataFrame, pd.Series]):
        from services.model_train_service.trainers.tcn_trainer import TCNTrainer
        X, y = data
        trainer = TCNTrainer(device="cpu", num_channels=[16, 16], seq_len=16)
        metrics = trainer.fit(X, y, epochs=3, batch_size=32)
        assert "val_loss" in metrics


class TestTFTTrainer:
    """Tests for TFTTrainer."""

    @pytest.fixture
    def data(self) -> tuple[pd.DataFrame, pd.Series]:
        np.random.seed(42)
        n = 200
        X = pd.DataFrame({f"f{i}": np.random.randn(n) for i in range(4)})
        y = pd.Series(np.random.randn(n) * 0.01)
        return X, y

    def test_fit_returns_metrics(self, data: tuple[pd.DataFrame, pd.Series]):
        from services.model_train_service.trainers.tft_trainer import TFTTrainer
        X, y = data
        trainer = TFTTrainer(device="cpu", hidden_dim=16, n_heads=2, seq_len=16)
        metrics = trainer.fit(X, y, epochs=3, batch_size=32, lr=0.001)
        assert "val_loss" in metrics

    def test_predict_quantiles(self, data: tuple[pd.DataFrame, pd.Series]):
        from services.model_train_service.trainers.tft_trainer import TFTTrainer
        X, y = data
        trainer = TFTTrainer(device="cpu", hidden_dim=16, n_heads=2, seq_len=16)
        trainer.fit(X, y, epochs=3, batch_size=32)
        qs = trainer.predict_quantiles(X)
        assert "q10" in qs
        assert "q50" in qs
        assert "q90" in qs


class TestRLTrainer:
    """Tests for RLTrainer (mock only — avoids gym dependencies)."""

    def test_mock_works_without_sb3(self):
        from services.model_train_service.trainers.rl_trainer import RLTrainer
        X = pd.DataFrame({f"f{i}": np.random.randn(50) for i in range(3)})
        y = pd.Series(np.random.randn(50) * 0.01)

        trainer = RLTrainer(device="cpu")
        metrics = trainer.fit(X, y)
        # Mock training should return zero-value metrics
        assert "mean_reward" in metrics
