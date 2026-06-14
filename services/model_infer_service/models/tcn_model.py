"""services/model_infer_service/models/tcn_model.py – TCN inference wrapper."""

from __future__ import annotations

import numpy as np
import pandas as pd
import torch
from loguru import logger

from services.model_infer_service.config import infer_config


class TCNInference:
    """TCN inference wrapper."""

    model_name = "tcn"

    def __init__(self, device: str | None = None) -> None:
        self.model: torch.nn.Module | None = None
        self.device = device or infer_config.DEVICE
        self.loaded = False
        self._feature_names: list[str] = []
        self._seq_len: int = 64

    def load(self, path: str) -> bool:
        """Load TCN model.

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

            from services.model_train_service.trainers.tcn_trainer import TCNModel

            self.model = TCNModel(
                n_features=config["n_features"],
                num_channels=config["num_channels"],
                kernel_size=config["kernel_size"],
                dropout=config["dropout"],
            ).to(self.device)
            self.model.load_state_dict(data["model_state"])
            self.model.eval()
            self.loaded = True
            logger.info(f"TCN model loaded from {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to load TCN: {e}")
            return False

    def predict(self, X: pd.DataFrame) -> np.ndarray:
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
