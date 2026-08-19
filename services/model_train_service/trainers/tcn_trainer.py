"""services/model_train_service/trainers/tcn_trainer.py – Temporal Convolutional Network trainer.

Dilated causal convolutions with residual connections + weight normalization.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from loguru import logger
from sklearn.preprocessing import StandardScaler
from torch.utils.data import DataLoader, TensorDataset

from services.model_train_service.config import train_config
from services.model_train_service.trainers.trainer_base import TrainerBase


class Chomp1d(nn.Module):
    """Trim the end of a tensor to ensure causal convolution."""

    def __init__(self, chomp_size: int) -> None:
        super().__init__()
        self.chomp_size = chomp_size

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x[:, :, :-self.chomp_size].contiguous()


class TCNBlock(nn.Module):
    """A single Temporal Block with dilated causal conv, weight norm, and residual connection."""

    def __init__(
        self,
        in_channels: int,
        out_channels: int,
        kernel_size: int,
        dilation: int,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        padding = (kernel_size - 1) * dilation

        self.conv1 = nn.utils.weight_norm(
            nn.Conv1d(in_channels, out_channels, kernel_size,
                       padding=padding, dilation=dilation)
        )
        self.chomp1 = Chomp1d(padding)
        self.relu1 = nn.ReLU()
        self.dropout1 = nn.Dropout(dropout)

        self.conv2 = nn.utils.weight_norm(
            nn.Conv1d(out_channels, out_channels, kernel_size,
                       padding=padding, dilation=dilation)
        )
        self.chomp2 = Chomp1d(padding)
        self.relu2 = nn.ReLU()
        self.dropout2 = nn.Dropout(dropout)

        self.downsample = nn.Conv1d(in_channels, out_channels, 1) if in_channels != out_channels else None
        self.relu = nn.ReLU()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        residual = x

        out = self.conv1(x)
        out = self.chomp1(out)
        out = self.relu1(out)
        out = self.dropout1(out)

        out = self.conv2(out)
        out = self.chomp2(out)
        out = self.relu2(out)
        out = self.dropout2(out)

        if self.downsample is not None:
            residual = self.downsample(x)

        return self.relu(out + residual)


class TCNModel(nn.Module):
    """Temporal Convolutional Network for sequence regression."""

    def __init__(
        self,
        n_features: int,
        num_channels: list[int] | None = None,
        kernel_size: int = 3,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        num_channels = num_channels or [64, 64, 64, 32]
        layers = []
        num_levels = len(num_channels)

        for i in range(num_levels):
            dilation = 2 ** i
            in_ch = n_features if i == 0 else num_channels[i - 1]
            out_ch = num_channels[i]
            layers.append(TCNBlock(in_ch, out_ch, kernel_size, dilation, dropout))

        self.network = nn.Sequential(*layers)
        self.fc = nn.Linear(num_channels[-1], 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq_len, n_features) → (batch, n_features, seq_len)
        x = x.permute(0, 2, 1)
        x = self.network(x)
        # Global average pooling over time
        x = x.mean(dim=2)
        return self.fc(x)


class TCNTrainer(TrainerBase):
    """TCN trainer with accelerated convergence via weight normalization."""

    model_name = "tcn"

    def __init__(
        self,
        num_channels: list[int] | None = None,
        kernel_size: int = 3,
        dropout: float = 0.2,
        seq_len: int = 64,
        device: str | None = None,
        lr: float | None = None,
    ) -> None:
        super().__init__(device=device or train_config.DEVICE)
        if num_channels is not None:
            self.num_channels = num_channels
        elif self.device == "cuda":
            ch = train_config.TCN_CHANNELS
            levels = train_config.TCN_LEVELS
            self.num_channels = [ch] * (levels - 1) + [ch // 2]
        else:
            self.num_channels = [32, 32, 32, 16]
        self.kernel_size = kernel_size
        self.dropout = dropout
        self.seq_len = seq_len
        self._lr = lr if lr is not None else 5e-5  # Lower default LR for TCN stability

    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        X_valid: pd.DataFrame | None = None,
        y_valid: pd.Series | None = None,
        **kwargs: Any,
    ) -> dict[str, float]:
        """Train the TCN model.

        Args:
            X: Training features.
            y: Training target.
            X_valid: Validation features.
            y_valid: Validation target.
            **kwargs: epochs, batch_size, lr.

        Returns:
            Training metrics.
        """
        self._validate_data(X, y)
        self._feature_names = list(X.columns)

        # ---- Feature normalization ----
        self._feature_scaler = StandardScaler()
        X_scaled = self._feature_scaler.fit_transform(X.values.astype(np.float64))

        # ── NaN safeguard ──
        X_arr = np.nan_to_num(X_scaled.astype(np.float32), nan=0.0, posinf=1.0, neginf=-1.0)
        y_arr = np.nan_to_num(y.values.astype(np.float32), nan=0.0, posinf=1.0, neginf=-1.0)

        epochs = kwargs.get("epochs", train_config.EPOCHS)
        batch_size = kwargs.get("batch_size", train_config.BATCH_SIZE)
        lr = kwargs.get("lr", self._lr)

        X_seqs, y_seqs = self._build_sequences(X_arr, y_arr)
        if X_valid is not None and y_valid is not None:
            X_v_scaled = self._feature_scaler.transform(X_valid.values.astype(np.float64))
            X_vs, y_vs = self._build_sequences(
                np.nan_to_num(X_v_scaled.astype(np.float32), nan=0.0, posinf=1.0, neginf=-1.0),
                np.nan_to_num(y_valid.values.astype(np.float32), nan=0.0, posinf=1.0, neginf=-1.0),
            )
        else:
            split = int(len(X_seqs) * 0.8)
            X_vs, y_vs = X_seqs[split:], y_seqs[split:]
            X_seqs, y_seqs = X_seqs[:split], y_seqs[:split]

        self.model = TCNModel(
            n_features=X.shape[1],
            num_channels=self.num_channels,
            kernel_size=self.kernel_size,
            dropout=self.dropout,
        ).to(self.device)

        optimizer = torch.optim.Adam(self.model.parameters(), lr=lr, weight_decay=1e-5)
        criterion = nn.MSELoss()

        train_ds = TensorDataset(
            torch.tensor(X_seqs, dtype=torch.float32),
            torch.tensor(y_seqs, dtype=torch.float32).unsqueeze(1),
        )
        val_ds = TensorDataset(
            torch.tensor(X_vs, dtype=torch.float32),
            torch.tensor(y_vs, dtype=torch.float32).unsqueeze(1),
        )
        train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True)
        val_loader = DataLoader(val_ds, batch_size=batch_size * 2)

        best_val_loss = float("inf")
        patience_counter = 0
        patience = train_config.EARLY_STOPPING_PATIENCE
        best_state = None
        train_losses: list[float] = []

        for epoch in range(epochs):
            self.model.train()
            epoch_loss = 0.0
            for batch_X, batch_y in train_loader:
                batch_X, batch_y = batch_X.to(self.device), batch_y.to(self.device)
                optimizer.zero_grad()
                loss = criterion(self.model(batch_X), batch_y)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                optimizer.step()
                epoch_loss += loss.item()

            avg_loss = epoch_loss / len(train_loader)
            train_losses.append(avg_loss)

            self.model.eval()
            val_loss = 0.0
            with torch.no_grad():
                for batch_X, batch_y in val_loader:
                    batch_X, batch_y = batch_X.to(self.device), batch_y.to(self.device)
                    val_loss += criterion(self.model(batch_X), batch_y).item()
            avg_val = val_loss / len(val_loader)

            if avg_val < best_val_loss:
                best_val_loss = avg_val
                best_state = {k: v.cpu().clone() for k, v in self.model.state_dict().items()}
                patience_counter = 0
            else:
                patience_counter += 1

            if patience_counter >= patience:
                logger.info(f"TCN early stopping at epoch {epoch+1}")
                break

        if best_state:
            self.model.load_state_dict(best_state)

        return {"train_loss": round(float(train_losses[-1]), 6), "val_loss": round(float(best_val_loss), 6),
                "epochs": len(train_losses)}

    def _build_sequences(self, X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        n = len(X) - self.seq_len
        if n < 1:
            raise ValueError(f"Not enough data: need >{self.seq_len}")
        X_seqs = np.array([X[i:i+self.seq_len] for i in range(n)], dtype=np.float32)
        y_seqs = np.array([y[i+self.seq_len-1] for i in range(n)], dtype=np.float32)
        return X_seqs, y_seqs

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if self.model is None:
            raise RuntimeError("Model not trained")
        if hasattr(self, '_feature_scaler') and self._feature_scaler is not None:
            X_arr = self._feature_scaler.transform(X.values.astype(np.float64))
            X_arr = np.nan_to_num(X_arr, nan=0.0, posinf=1.0, neginf=-1.0).astype(np.float32)
        else:
            X_arr = X.values.astype(np.float32)
        X_seqs, _ = self._build_sequences(X_arr, np.zeros(len(X_arr)))
        self.model.eval()
        with torch.no_grad():
            X_t = torch.tensor(X_seqs, dtype=torch.float32).to(self.device)
            pred = self.model(X_t).cpu().numpy().ravel()
        padded = np.zeros(len(X_arr))
        padded[:len(pred)] = pred
        return padded

    def save(self, path: str) -> None:
        import os
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        torch.save({
            "model_state": self.model.state_dict(),
            "config": {"n_features": len(self._feature_names), "num_channels": self.num_channels,
                       "kernel_size": self.kernel_size, "dropout": self.dropout, "seq_len": self.seq_len},
            "feature_names": self._feature_names,
            "scaler": self._feature_scaler if hasattr(self, '_feature_scaler') else None,
        }, path)
        logger.info(f"TCN model saved to {path}")

    def load(self, path: str) -> None:
        data = torch.load(path, map_location=self.device)
        config = data["config"]
        self._feature_names = data.get("feature_names", [])
        self._feature_scaler = data.get("scaler", None)
        self.model = TCNModel(
            n_features=config["n_features"], num_channels=config["num_channels"],
            kernel_size=config["kernel_size"], dropout=config["dropout"],
        ).to(self.device)
        self.model.load_state_dict(data["model_state"])
        self.model.eval()
        logger.info(f"TCN model loaded from {path}")
