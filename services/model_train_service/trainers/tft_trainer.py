"""services/model_train_service/trainers/tft_trainer.py – Temporal Fusion Transformer trainer.

Google Research TFT: variable selection networks, LSTM encoder-decoder,
multi-head attention, and quantile output [0.1, 0.5, 0.9].
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from loguru import logger
from torch.utils.data import DataLoader, TensorDataset

from services.model_train_service.config import train_config
from services.model_train_service.trainers.trainer_base import TrainerBase


class VariableSelectionNetwork(nn.Module):
    """Per-variable feature selection with gated residual network."""

    def __init__(self, input_dim: int, hidden_dim: int, dropout: float = 0.1) -> None:
        super().__init__()
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim

        self.weight_net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, input_dim),
            nn.Softmax(dim=-1),
        )
        self.transform = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        weights = self.weight_net(x)
        selected = x * weights
        return self.transform(selected)


class GatedResidualNetwork(nn.Module):
    """Gated Residual Network with GLU."""

    def __init__(self, input_dim: int, hidden_dim: int, output_dim: int | None = None,
                 dropout: float = 0.1) -> None:
        super().__init__()
        output_dim = output_dim or input_dim

        self.fc1 = nn.Linear(input_dim, hidden_dim)
        self.elu = nn.ELU()
        self.fc2 = nn.Linear(hidden_dim, output_dim * 2)
        self.dropout = nn.Dropout(dropout)
        self.gate = nn.GLU(dim=-1)

        if input_dim != output_dim:
            self.residual = nn.Linear(input_dim, output_dim)
        else:
            self.residual = nn.Identity()

        self.layer_norm = nn.LayerNorm(output_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        residual = self.residual(x)
        out = self.fc2(self.dropout(self.elu(self.fc1(x))))
        out = self.gate(out)
        return self.layer_norm(out + residual)


class TFTModel(nn.Module):
    """Temporal Fusion Transformer for quantile forecasting."""

    def __init__(
        self,
        n_features: int,
        hidden_dim: int = 64,
        n_heads: int = 4,
        lstm_layers: int = 1,
        dropout: float = 0.1,
        seq_len: int = 64,
        quantiles: list[float] | None = None,
    ) -> None:
        super().__init__()
        self.quantiles = quantiles or [0.1, 0.5, 0.9]
        self.n_quantiles = len(self.quantiles)

        self.vsn = VariableSelectionNetwork(n_features, hidden_dim, dropout)
        self.lstm = nn.LSTM(hidden_dim, hidden_dim, num_layers=lstm_layers,
                            batch_first=True, bidirectional=False)

        self.attention = nn.MultiheadAttention(hidden_dim, n_heads,
                                               dropout=dropout, batch_first=True)

        self.post_attn_grn = GatedResidualNetwork(hidden_dim, hidden_dim, hidden_dim * 2, dropout)
        # post_attn_grn outputs hidden_dim*2, so output_grn must accept that as input
        self.output_grn = GatedResidualNetwork(hidden_dim * 2, hidden_dim * 2, hidden_dim, dropout)
        self.quantile_heads = nn.ModuleList([
            nn.Linear(hidden_dim, 1) for _ in range(self.n_quantiles)
        ])

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq_len, n_features)
        x = self.vsn(x)
        lstm_out, _ = self.lstm(x)

        attn_out, _ = self.attention(lstm_out, lstm_out, lstm_out)
        attn_out = self.post_attn_grn(attn_out[:, -1, :])

        enriched = self.output_grn(attn_out)

        outputs = [head(enriched) for head in self.quantile_heads]
        return torch.cat(outputs, dim=-1)  # (batch, n_quantiles)


class TFTTrainer(TrainerBase):
    """TFT trainer producing quantile forecasts [0.1, 0.5, 0.9]."""

    model_name = "tft"

    def __init__(
        self,
        hidden_dim: int = 64,
        n_heads: int = 4,
        lstm_layers: int = 1,
        dropout: float = 0.1,
        seq_len: int = 64,
        device: str | None = None,
    ) -> None:
        super().__init__(device=device or train_config.DEVICE)
        self.hidden_dim = hidden_dim
        self.n_heads = n_heads
        self.lstm_layers = lstm_layers
        self.dropout = dropout
        self.seq_len = seq_len

    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        X_valid: pd.DataFrame | None = None,
        y_valid: pd.Series | None = None,
        **kwargs: Any,
    ) -> dict[str, float]:
        """Train the TFT model.

        Returns:
            Training metrics.
        """
        self._validate_data(X, y)
        self._feature_names = list(X.columns)

        epochs = kwargs.get("epochs", train_config.EPOCHS)
        batch_size = kwargs.get("batch_size", train_config.BATCH_SIZE)
        lr = kwargs.get("lr", train_config.LEARNING_RATE)

        X_seqs, y_seqs = self._build_sequences(X.values, y.values)
        if X_valid is not None and y_valid is not None:
            X_vs, y_vs = self._build_sequences(X_valid.values, y_valid.values)
        else:
            split = int(len(X_seqs) * 0.8)
            X_vs, y_vs = X_seqs[split:], y_seqs[split:]
            X_seqs, y_seqs = X_seqs[:split], y_seqs[:split]

        self.model = TFTModel(
            n_features=X.shape[1], hidden_dim=self.hidden_dim,
            n_heads=self.n_heads, lstm_layers=self.lstm_layers,
            dropout=self.dropout, seq_len=self.seq_len,
        ).to(self.device)

        optimizer = torch.optim.AdamW(self.model.parameters(), lr=lr, weight_decay=1e-5)
        criterion = nn.MSELoss()  # Simplified: use MSE on median quantile

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
                pred = self.model(batch_X)
                # Use median quantile (index 1) for loss
                loss = criterion(pred[:, 1:2], batch_y)
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
                    pred = self.model(batch_X)
                    val_loss += criterion(pred[:, 1:2], batch_y).item()
            avg_val = val_loss / len(val_loader)

            if avg_val < best_val_loss:
                best_val_loss = avg_val
                best_state = {k: v.cpu().clone() for k, v in self.model.state_dict().items()}
                patience_counter = 0
            else:
                patience_counter += 1
            if patience_counter >= patience:
                logger.info(f"TFT early stopping at epoch {epoch+1}")
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
        """Return median quantile predictions."""
        if self.model is None:
            raise RuntimeError("Model not trained")
        X_arr = X.values.astype(np.float32)
        X_seqs, _ = self._build_sequences(X_arr, np.zeros(len(X_arr)))
        self.model.eval()
        with torch.no_grad():
            X_t = torch.tensor(X_seqs, dtype=torch.float32).to(self.device)
            pred = self.model(X_t).cpu().numpy()
        # Return median (index 1)
        pred_median = pred[:, 1]
        padded = np.zeros(len(X_arr))
        padded[:len(pred_median)] = pred_median
        return padded

    def predict_quantiles(self, X: pd.DataFrame) -> dict[str, np.ndarray]:
        """Return all quantile predictions.

        Returns:
            Dict mapping 'q10', 'q50', 'q90' → prediction arrays.
        """
        if self.model is None:
            raise RuntimeError("Model not trained")
        X_arr = X.values.astype(np.float32)
        X_seqs, _ = self._build_sequences(X_arr, np.zeros(len(X_arr)))
        self.model.eval()
        with torch.no_grad():
            X_t = torch.tensor(X_seqs, dtype=torch.float32).to(self.device)
            pred = self.model(X_t).cpu().numpy()
        return {
            "q10": self._pad(pred[:, 0], len(X_arr)),
            "q50": self._pad(pred[:, 1], len(X_arr)),
            "q90": self._pad(pred[:, 2], len(X_arr)),
        }

    def _pad(self, arr: np.ndarray, target_len: int) -> np.ndarray:
        padded = np.zeros(target_len)
        padded[:len(arr)] = arr
        return padded

    def save(self, path: str) -> None:
        import os
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        torch.save({"model_state": self.model.state_dict(),
                     "config": {"n_features": len(self._feature_names), "hidden_dim": self.hidden_dim,
                                "n_heads": self.n_heads, "lstm_layers": self.lstm_layers,
                                "dropout": self.dropout, "seq_len": self.seq_len},
                     "feature_names": self._feature_names}, path)
        logger.info(f"TFT model saved to {path}")

    def load(self, path: str) -> None:
        data = torch.load(path, map_location=self.device)
        config = data["config"]
        self._feature_names = data.get("feature_names", [])
        self.model = TFTModel(n_features=config["n_features"], hidden_dim=config["hidden_dim"],
                              n_heads=config["n_heads"], lstm_layers=config["lstm_layers"],
                              dropout=config["dropout"], seq_len=config["seq_len"]).to(self.device)
        self.model.load_state_dict(data["model_state"])
        self.model.eval()
        logger.info(f"TFT model loaded from {path}")
