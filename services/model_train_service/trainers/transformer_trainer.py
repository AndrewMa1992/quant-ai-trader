"""services/model_train_service/trainers/transformer_trainer.py – PatchTST-style Transformer.

d_model=128(CPU)/512(GPU), n_heads=8, n_layers=4/6, dropout=0.1.
Positional encoding, gradient clipping=1.0, warmup LR schedule.
"""

from __future__ import annotations

import math
from typing import Any, Optional

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from loguru import logger
from torch.utils.data import DataLoader, TensorDataset

from services.model_train_service.config import train_config
from services.model_train_service.trainers.trainer_base import TrainerBase


class PositionalEncoding(nn.Module):
    """Sinusoidal positional encoding."""

    def __init__(self, d_model: int, max_len: int = 5000, dropout: float = 0.1) -> None:
        super().__init__()
        self.dropout = nn.Dropout(p=dropout)
        position = torch.arange(max_len).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2) * (-math.log(10000.0) / d_model))
        pe = torch.zeros(max_len, d_model)
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        self.register_buffer("pe", pe)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        seq_len = x.size(1)
        return self.dropout(x + self.pe[:seq_len, :])


class PatchTSTEncoder(nn.Module):
    """PatchTST-style Transformer encoder."""

    def __init__(
        self,
        d_model: int = 128,
        n_heads: int = 8,
        n_layers: int = 4,
        dropout: float = 0.1,
        dim_feedforward: int = 512,
    ) -> None:
        super().__init__()
        self.pos_encoder = PositionalEncoding(d_model, dropout=dropout)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=n_heads,
            dim_feedforward=dim_feedforward,
            dropout=dropout,
            batch_first=True,
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.transformer(self.pos_encoder(x))


class PatchTSTRegressor(nn.Module):
    """PatchTST model for time series regression."""

    def __init__(
        self,
        n_features: int,
        d_model: int = 128,
        n_heads: int = 8,
        n_layers: int = 4,
        dropout: float = 0.1,
        seq_len: int = 64,
        forecast_horizon: int = 1,
    ) -> None:
        super().__init__()
        self.seq_len = seq_len
        self.input_proj = nn.Linear(n_features, d_model)
        self.encoder = PatchTSTEncoder(
            d_model=d_model, n_heads=n_heads, n_layers=n_layers, dropout=dropout,
            dim_feedforward=d_model * 4,
        )
        self.head = nn.Sequential(
            nn.LayerNorm(d_model),
            nn.Linear(d_model, d_model // 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(d_model // 2, forecast_horizon),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq_len, n_features)
        x = self.input_proj(x)
        x = self.encoder(x)
        # Pool across time: use last token
        x = x[:, -1, :]
        return self.head(x)


class TransformerTrainer(TrainerBase):
    """PatchTST-style Transformer trainer.

    Auto-selects d_model based on device:
    - CPU: d_model=128, n_layers=4
    - GPU: d_model=512, n_layers=6

    Supports gradient clipping and warmup cosine LR schedule.
    """

    model_name = "transformer"

    def __init__(
        self,
        d_model: int | None = None,
        n_heads: int = 8,
        n_layers: int | None = None,
        dropout: float = 0.1,
        seq_len: int = 64,
        forecast_horizon: int = 1,
        device: str | None = None,
    ) -> None:
        super().__init__(device=device or train_config.DEVICE)
        self.d_model = d_model or (
            train_config.TRANSFORMER_D_MODEL_GPU if self.device == "cuda"
            else train_config.TRANSFORMER_D_MODEL_CPU
        )
        self.n_heads = n_heads
        self.n_layers = n_layers or (6 if self.device == "cuda" else 4)
        self.dropout = dropout
        self.seq_len = seq_len
        self.forecast_horizon = forecast_horizon
        self._grad_clip = train_config.GRADIENT_CLIP_VAL

    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        X_valid: pd.DataFrame | None = None,
        y_valid: pd.Series | None = None,
        **kwargs: Any,
    ) -> dict[str, float]:
        """Train the Transformer model.

        Args:
            X: Training features.
            y: Training target.
            X_valid: Validation features.
            y_valid: Validation target.
            **kwargs: Override defaults (epochs, batch_size, lr).

        Returns:
            Training metrics.
        """
        self._validate_data(X, y)
        if hasattr(X, 'columns'):
            self._feature_names = list(X.columns)
        else:
            n = kwargs.get("n_vars", X.shape[-1] if hasattr(X, 'shape') else len(X.columns))
            self._feature_names = [f"f{i}" for i in range(n)]

        epochs = kwargs.get("epochs", train_config.EPOCHS)
        batch_size = kwargs.get("batch_size", train_config.BATCH_SIZE)
        lr = kwargs.get("lr", train_config.LEARNING_RATE)

        # Build sequences
        X_train, y_train = self._build_sequences(X.values, y.values)
        if X_valid is not None and y_valid is not None:
            X_val, y_val = self._build_sequences(X_valid.values, y_valid.values)
        else:
            split = int(len(X_train) * 0.8)
            X_val, y_val = X_train[split:], y_train[split:]
            X_train, y_train = X_train[:split], y_train[:split]

        # PyTorch model
        self.model = PatchTSTRegressor(
            n_features=X.shape[1],
            d_model=self.d_model,
            n_heads=self.n_heads,
            n_layers=self.n_layers,
            dropout=self.dropout,
            seq_len=self.seq_len,
            forecast_horizon=self.forecast_horizon,
        ).to(self.device)

        optimizer = torch.optim.AdamW(self.model.parameters(), lr=lr, weight_decay=1e-5)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingWarmRestarts(optimizer, T_0=10, T_mult=2)
        criterion = nn.MSELoss()

        train_ds = TensorDataset(
            torch.tensor(X_train, dtype=torch.float32),
            torch.tensor(y_train, dtype=torch.float32).unsqueeze(1),
        )
        val_ds = TensorDataset(
            torch.tensor(X_val, dtype=torch.float32),
            torch.tensor(y_val, dtype=torch.float32).unsqueeze(1),
        )
        train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True)
        val_loader = DataLoader(val_ds, batch_size=batch_size * 2)

        best_val_loss = float("inf")
        patience_counter = 0
        patience = train_config.EARLY_STOPPING_PATIENCE
        best_state = None

        train_losses: list[float] = []
        val_losses: list[float] = []

        for epoch in range(epochs):
            self.model.train()
            epoch_loss = 0.0

            for batch_X, batch_y in train_loader:
                batch_X, batch_y = batch_X.to(self.device), batch_y.to(self.device)
                optimizer.zero_grad()
                pred = self.model(batch_X)
                loss = criterion(pred, batch_y)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), self._grad_clip)
                optimizer.step()
                epoch_loss += loss.item()

            avg_train_loss = epoch_loss / len(train_loader)
            train_losses.append(avg_train_loss)

            # Validation
            self.model.eval()
            val_loss = 0.0
            with torch.no_grad():
                for batch_X, batch_y in val_loader:
                    batch_X, batch_y = batch_X.to(self.device), batch_y.to(self.device)
                    pred = self.model(batch_X)
                    val_loss += criterion(pred, batch_y).item()

            avg_val_loss = val_loss / len(val_loader)
            val_losses.append(avg_val_loss)
            scheduler.step()

            if avg_val_loss < best_val_loss:
                best_val_loss = avg_val_loss
                best_state = {k: v.cpu().clone() for k, v in self.model.state_dict().items()}
                patience_counter = 0
            else:
                patience_counter += 1

            if (epoch + 1) % 10 == 0:
                logger.debug(f"Epoch {epoch+1}/{epochs}: train_loss={avg_train_loss:.6f}, val_loss={avg_val_loss:.6f}")

            if patience_counter >= patience:
                logger.info(f"Early stopping at epoch {epoch+1}")
                break

        if best_state is not None:
            self.model.load_state_dict(best_state)

        return {
            "train_loss": round(float(train_losses[-1]), 6),
            "val_loss": round(float(best_val_loss), 6),
            "epochs": len(train_losses),
        }

    def _build_sequences(
        self,
        X: np.ndarray,
        y: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Build time-series sequences for Transformer input.

        Args:
            X: Feature array (n_samples, n_features).
            y: Target array (n_samples,).

        Returns:
            (X_seqs, y_seqs) where X_seqs has shape (n_seqs, seq_len, n_features).
        """
        n = len(X) - self.seq_len
        if n < 1:
            raise ValueError(f"Not enough data: need >{self.seq_len}, got {len(X)}")

        X_seqs = np.array([X[i : i + self.seq_len] for i in range(n)], dtype=np.float32)
        y_seqs = np.array([y[i + self.seq_len - 1] for i in range(n)], dtype=np.float32)
        return X_seqs, y_seqs

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Generate predictions.

        Args:
            X: Feature matrix.

        Returns:
            Prediction array.
        """
        if self.model is None:
            raise RuntimeError("Model not trained")

        X_arr = X.values.astype(np.float32)
        X_seqs, _ = self._build_sequences(X_arr, np.zeros(len(X_arr)))

        self.model.eval()
        with torch.no_grad():
            X_t = torch.tensor(X_seqs, dtype=torch.float32).to(self.device)
            pred = self.model(X_t).cpu().numpy().ravel()

        # Pad to original length
        padded = np.zeros(len(X_arr))
        padded[:len(pred)] = pred
        return padded

    def save(self, path: str) -> None:
        """Save model state."""
        import os
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        torch.save({
            "model_state": self.model.state_dict(),
            "config": {
                "n_features": len(self._feature_names),
                "d_model": self.d_model,
                "n_heads": self.n_heads,
                "n_layers": self.n_layers,
                "dropout": self.dropout,
                "seq_len": self.seq_len,
            },
            "feature_names": self._feature_names,
        }, path)
        logger.info(f"Transformer model saved to {path}")

    def load(self, path: str) -> None:
        """Load model state."""
        data = torch.load(path, map_location=self.device)
        config = data["config"]
        self._feature_names = data.get("feature_names", [])

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
        logger.info(f"Transformer model loaded from {path}")
