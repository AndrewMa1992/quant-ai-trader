"""services/model_infer_service/models/tcn_model.py – TCN inference wrapper."""

from __future__ import annotations

import numpy as np
import pandas as pd
import torch
from loguru import logger

from services.model_infer_service.config import infer_config
from services.model_infer_service.models.preprocess import (
    align_features,
    apply_scaler,
    build_rolling_sequences,
    load_checkpoint_meta,
)


class TCNInference:
    """TCN inference wrapper."""

    model_name = "tcn"

    def __init__(self, device: str | None = None) -> None:
        self.model: torch.nn.Module | None = None
        self.device = device or infer_config.DEVICE
        self.loaded = False
        self._feature_names: list[str] = []
        self._seq_len: int = 64
        self._scaler = None
        self.last_missing_fraction: float = 0.0

    def load(self, path: str) -> bool:
        """Load TCN model."""
        try:
            data = torch.load(path, map_location=self.device, weights_only=False)
            self._feature_names, self._scaler, config = load_checkpoint_meta(data)
            self._seq_len = int(config.get("seq_len", 64))

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
            logger.info(
                f"TCN loaded from {path} "
                f"(scaler={'yes' if self._scaler is not None else 'no'})"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to load TCN: {e}")
            return False

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if not self.loaded or self.model is None:
            return np.zeros(len(X))

        aligned, miss = align_features(X, self._feature_names or list(X.columns))
        self.last_missing_fraction = miss
        X_arr = apply_scaler(aligned, self._scaler)
        seqs = build_rolling_sequences(X_arr, self._seq_len)
        if len(seqs) == 0:
            return np.zeros(len(X))

        with torch.no_grad():
            X_t = torch.tensor(seqs, dtype=torch.float32).to(self.device)
            pred = self.model(X_t).cpu().numpy().ravel()
        pred = np.clip(pred, -1.0, 1.0)
        padded = np.zeros(len(X))
        padded[-len(pred) :] = pred
        return padded
