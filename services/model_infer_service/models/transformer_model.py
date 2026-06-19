"""services/model_infer_service/models/transformer_model.py – Transformer inference wrapper.

Loads PatchTST model and predicts future n-step returns.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import torch
from loguru import logger

from services.model_infer_service.config import infer_config


class TransformerInference:
    """PatchTST Transformer inference wrapper."""

    model_name = "transformer"

    def __init__(self, device: str | None = None) -> None:
        self.model: torch.nn.Module | None = None
        self.device = device or infer_config.DEVICE
        self.loaded = False
        self._feature_names: list[str] = []
        self._seq_len: int = 64
        self._config: dict = {}

    def load(self, path: str) -> bool:
        """Load model from checkpoint.

        Args:
            path: File path to .pt checkpoint.

        Returns:
            True if loaded.
        """
        try:
            data = torch.load(path, map_location=self.device)
            config = data["config"]
            self._feature_names = data.get("feature_names", [])
            self._seq_len = config["seq_len"]
            self._config = config

            from services.model_train_service.trainers.transformer_trainer import PatchTSTRegressor

            self.model = PatchTSTRegressor(
                n_features=config["n_features"],
                d_model=config["d_model"],
                n_heads=config["n_heads"],
                n_layers=config["n_layers"],
                dropout=config["dropout"],
                seq_len=config["seq_len"],
            ).to(self.device)
            self.model.load_state_dict(data["model_state"])
            self.model.eval()
            self.loaded = True

            logger.info(f"Transformer model loaded from {path}")
            return True

        except Exception as e:
            logger.error(f"Failed to load Transformer model: {e}")
            return False

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Generate future return predictions.

        Args:
            X: Feature matrix.

        Returns:
            Predicted future returns.
        """
        if not self.loaded or self.model is None:
            return np.zeros(len(X))

        X_arr = X.values.astype(np.float32)
        n = len(X_arr) - self._seq_len
        if n < 1:
            return np.zeros(len(X_arr))

        X_seqs = np.array([X_arr[i:i+self._seq_len] for i in range(n)], dtype=np.float32)

        with torch.no_grad():
            X_t = torch.tensor(X_seqs, dtype=torch.float32).to(self.device)
            pred = self.model(X_t).cpu().numpy().ravel()

        padded = np.zeros(len(X_arr))
        padded[:len(pred)] = pred
        return padded
