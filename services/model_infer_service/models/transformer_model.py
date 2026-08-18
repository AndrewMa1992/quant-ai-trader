"""services/model_infer_service/models/transformer_model.py – Transformer inference wrapper.

Loads PatchTST model and predicts future n-step returns.
Applies training-time StandardScaler when present in the checkpoint.
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
        self._scaler = None
        self.last_missing_fraction: float = 0.0

    def load(self, path: str) -> bool:
        """Load model from checkpoint."""
        try:
            data = torch.load(path, map_location=self.device, weights_only=False)
            self._feature_names, self._scaler, config = load_checkpoint_meta(data)
            self._seq_len = int(config.get("seq_len", 64))
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
            logger.info(
                f"Transformer loaded from {path} "
                f"(scaler={'yes' if self._scaler is not None else 'no'}, "
                f"feats={len(self._feature_names)})"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to load Transformer model: {e}")
            return False

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Generate future return predictions."""
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

        padded = np.zeros(len(X))
        padded[-len(pred) :] = pred
        return padded
