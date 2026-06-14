"""services/model_infer_service/models/tft_model.py – TFT inference wrapper.

Outputs quantile predictions (10%/50%/90%).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import torch
from loguru import logger

from services.model_infer_service.config import infer_config


class TFTInference:
    """TFT inference wrapper with quantile predictions."""

    model_name = "tft"

    def __init__(self, device: str | None = None) -> None:
        self.model: torch.nn.Module | None = None
        self.device = device or infer_config.DEVICE
        self.loaded = False
        self._feature_names: list[str] = []
        self._seq_len: int = 64

    def load(self, path: str) -> bool:
        """Load TFT model.

        Args:
            path: Checkpoint path.

        Returns:
            True if loaded.
        """
        try:
            data = torch.load(path, map_location=self.device)
            config = data["config"]
            self._feature_names = data.get("feature_names", [])
            self._seq_len = config["seq_len"]

            from services.model_train_service.trainers.tft_trainer import TFTModel

            self.model = TFTModel(
                n_features=config["n_features"],
                hidden_dim=config["hidden_dim"],
                n_heads=config["n_heads"],
                lstm_layers=config["lstm_layers"],
                dropout=config["dropout"],
                seq_len=config["seq_len"],
            ).to(self.device)
            self.model.load_state_dict(data["model_state"])
            self.model.eval()
            self.loaded = True
            logger.info(f"TFT model loaded from {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to load TFT: {e}")
            return False

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Return median quantile predictions."""
        qs = self.predict_quantiles(X)
        return qs["q50"]

    def predict_quantiles(self, X: pd.DataFrame) -> dict[str, np.ndarray]:
        """Return all quantile predictions.

        Returns:
            Dict with 'q10', 'q50', 'q90' → arrays.
        """
        if not self.loaded or self.model is None:
            n = len(X)
            return {"q10": np.zeros(n), "q50": np.zeros(n), "q90": np.zeros(n)}

        X_arr = X.values.astype(np.float32)
        n = len(X_arr) - self._seq_len
        if n < 1:
            nz = np.zeros(len(X_arr))
            return {"q10": nz, "q50": nz, "q90": nz}

        X_seqs = np.array([X_arr[i:i+self._seq_len] for i in range(n)], dtype=np.float32)

        with torch.no_grad():
            X_t = torch.tensor(X_seqs, dtype=torch.float32).to(self.device)
            pred = self.model(X_t).cpu().numpy()

        result = {}
        for i, key in enumerate(["q10", "q50", "q90"]):
            padded = np.zeros(len(X_arr))
            padded[:len(pred)] = pred[:, i]
            result[key] = padded

        return result
