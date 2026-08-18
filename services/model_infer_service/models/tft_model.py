"""services/model_infer_service/models/tft_model.py – TFT inference wrapper.

Outputs quantile predictions (10%/50%/90%). Applies train-time scaler when saved.
"""

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


class TFTInference:
    """TFT inference wrapper with quantile predictions."""

    model_name = "tft"

    def __init__(self, device: str | None = None) -> None:
        self.model: torch.nn.Module | None = None
        self.device = device or infer_config.DEVICE
        self.loaded = False
        self._feature_names: list[str] = []
        self._seq_len: int = 64
        self._scaler = None
        self.last_missing_fraction: float = 0.0

    def load(self, path: str) -> bool:
        """Load TFT model."""
        try:
            data = torch.load(path, map_location=self.device, weights_only=False)
            self._feature_names, self._scaler, config = load_checkpoint_meta(data)
            self._seq_len = int(config.get("seq_len", 64))

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
            logger.info(
                f"TFT loaded from {path} "
                f"(scaler={'yes' if self._scaler is not None else 'no'})"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to load TFT: {e}")
            return False

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Return median quantile predictions."""
        qs = self.predict_quantiles(X)
        return qs["q50"]

    def predict_quantiles(self, X: pd.DataFrame) -> dict[str, np.ndarray]:
        """Return all quantile predictions."""
        if not self.loaded or self.model is None:
            n = len(X)
            return {"q10": np.zeros(n), "q50": np.zeros(n), "q90": np.zeros(n)}

        aligned, miss = align_features(X, self._feature_names or list(X.columns))
        self.last_missing_fraction = miss
        X_arr = apply_scaler(aligned, self._scaler)
        seqs = build_rolling_sequences(X_arr, self._seq_len)
        if len(seqs) == 0:
            nz = np.zeros(len(X))
            return {"q10": nz, "q50": nz, "q90": nz}

        with torch.no_grad():
            X_t = torch.tensor(seqs, dtype=torch.float32).to(self.device)
            pred = self.model(X_t).cpu().numpy()

        result = {}
        for i, key in enumerate(["q10", "q50", "q90"]):
            padded = np.zeros(len(X))
            padded[-len(pred) :] = pred[:, i]
            result[key] = padded
        return result
