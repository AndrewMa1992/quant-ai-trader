"""
Transformer / PatchTST 价格预测器
基于 PyTorch 的时间序列 Transformer
"""
import math
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset
from loguru import logger
from backend.config import model_config, MODELS_DIR


class PatchEmbedding(nn.Module):
    def __init__(self, d_model, patch_len, stride, dropout=0.1):
        super().__init__()
        self.patch_len = patch_len
        self.stride = stride
        self.linear = nn.Linear(patch_len, d_model)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x):
        batch, n_vars, seq_len = x.shape
        patches = x.unfold(dimension=2, size=self.patch_len, step=self.stride)
        patches = self.linear(patches)
        return self.dropout(patches)


class MultiHeadSelfAttention(nn.Module):
    def __init__(self, d_model, n_heads, dropout=0.1):
        super().__init__()
        assert d_model % n_heads == 0
        self.d_k = d_model // n_heads
        self.n_heads = n_heads
        self.W_q = nn.Linear(d_model, d_model)
        self.W_k = nn.Linear(d_model, d_model)
        self.W_v = nn.Linear(d_model, d_model)
        self.W_o = nn.Linear(d_model, d_model)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x):
        batch, n_vars, n_patches, d_model = x.shape
        x = x.view(batch * n_vars, n_patches, d_model)
        Q = self.W_q(x).view(-1, n_patches, self.n_heads, self.d_k).transpose(1, 2)
        K = self.W_k(x).view(-1, n_patches, self.n_heads, self.d_k).transpose(1, 2)
        V = self.W_v(x).view(-1, n_patches, self.n_heads, self.d_k).transpose(1, 2)
        scores = torch.matmul(Q, K.transpose(-2, -1)) / math.sqrt(self.d_k)
        attn = F.softmax(scores, dim=-1)
        attn = self.dropout(attn)
        out = torch.matmul(attn, V).transpose(1, 2).contiguous()
        out = out.view(batch * n_vars, n_patches, d_model)
        return self.W_o(out).view(batch, n_vars, n_patches, d_model)


class TransformerEncoderLayer(nn.Module):
    def __init__(self, d_model, n_heads, d_ff, dropout=0.1):
        super().__init__()
        self.attention = MultiHeadSelfAttention(d_model, n_heads, dropout)
        self.ff = nn.Sequential(
            nn.Linear(d_model, d_ff), nn.GELU(), nn.Dropout(dropout), nn.Linear(d_ff, d_model)
        )
        self.norm1 = nn.LayerNorm(d_model)
        self.norm2 = nn.LayerNorm(d_model)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x):
        x = self.norm1(x + self.dropout(self.attention(x)))
        x = self.norm2(x + self.dropout(self.ff(x)))
        return x


class PatchTST(nn.Module):
    def __init__(self, n_vars=40, seq_len=60, pred_len=5, patch_len=12, stride=8,
                 d_model=128, n_heads=8, n_layers=4, d_ff=256, dropout=0.1, n_quantiles=3):
        super().__init__()
        self.seq_len, self.pred_len, self.n_vars = seq_len, pred_len, n_vars
        self.n_patches = ((seq_len - patch_len) // stride) + 1
        self.patch_embedding = PatchEmbedding(d_model, patch_len, stride, dropout)
        self.pos_encoding = nn.Parameter(torch.randn(1, 1, self.n_patches, d_model) * 0.02)
        self.encoder_layers = nn.ModuleList([
            TransformerEncoderLayer(d_model, n_heads, d_ff, dropout) for _ in range(n_layers)
        ])
        self.head = nn.Linear(d_model * self.n_patches, pred_len * n_quantiles)
        self._init_weights()

    def _init_weights(self):
        for p in self.parameters():
            if p.dim() > 1:
                nn.init.xavier_uniform_(p)

    def forward(self, x):
        x = self.patch_embedding(x) + self.pos_encoding[:, :, :self.n_patches, :]
        batch, n_vars, n_patches, d_model = x.shape
        x_flat = x.view(batch * n_vars, n_patches, d_model)
        for layer in self.encoder_layers:
            x_flat = x_flat.view(batch, n_vars, n_patches, d_model)
            x_flat = layer(x_flat)
            x_flat = x_flat.view(batch * n_vars, n_patches, d_model)
        x_out = x_flat.view(batch, n_vars, n_patches * d_model)
        x_out = self.head(x_out).view(batch, n_vars, self.pred_len, 3)
        x_out = x_out.mean(dim=1)
        return torch.sort(x_out, dim=-1).values


class TransformerPredictor:
    def __init__(self):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = None
        self.scaler_mean = None
        self.scaler_std = None
        self._is_trained = False
        logger.info(f"Transformer 预测器初始化 (device: {self.device})")

    def build_model(self, n_vars=40, seq_len=60, pred_len=5):
        self.model = PatchTST(
            n_vars=n_vars, seq_len=seq_len, pred_len=pred_len,
            patch_len=model_config.TRANSFORMER_LOOKBACK // 5,
            stride=model_config.TRANSFORMER_LOOKBACK // 8,
            d_model=model_config.TRANSFORMER_D_MODEL,
            n_heads=model_config.TRANSFORMER_N_HEADS,
            n_layers=model_config.TRANSFORMER_N_LAYERS,
        ).to(self.device)
        logger.info(f"模型构建: {sum(p.numel() for p in self.model.parameters()):,} 参数")
        return self.model

    def train(self, X_train, y_train, X_val=None, y_val=None, n_vars=40):
        self.build_model(n_vars=n_vars)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = self.model.to(self.device)

        # 清理 NaN/Inf
        X_train = np.nan_to_num(X_train, nan=0.0, posinf=1.0, neginf=-1.0)
        y_train = np.nan_to_num(y_train, nan=0.0, posinf=1.0, neginf=-1.0)

        self.scaler_mean = X_train.mean(axis=(0, 1))
        self.scaler_std = X_train.std(axis=(0, 1)) + 1e-8
        X_norm = (X_train - self.scaler_mean) / self.scaler_std
        X_norm = np.clip(X_norm, -10, 10)  # 限制异常值

        y_mean = y_train.mean()
        y_std = y_train.std() + 1e-8
        y_norm = (y_train - y_mean) / y_std

        X_t = torch.FloatTensor(X_norm).permute(0, 2, 1).to(self.device)
        # 目标: (batch, pred_len, 3) 3个分位数
        y_t = torch.FloatTensor(y_norm).unsqueeze(-1).expand(-1, -1, 3).contiguous().to(self.device)

        loader = DataLoader(TensorDataset(X_t, y_t), batch_size=model_config.TRANSFORMER_BATCH_SIZE, shuffle=True)
        optimizer = torch.optim.AdamW(self.model.parameters(), lr=model_config.TRANSFORMER_LEARNING_RATE)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=model_config.TRANSFORMER_EPOCHS)

        self.model.train()
        for epoch in range(model_config.TRANSFORMER_EPOCHS):
            loss_total = 0
            for bx, by in loader:
                optimizer.zero_grad()
                pred = self.model(bx)
                loss = F.smooth_l1_loss(pred[:, :, 1], by[:, :, 1])
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                optimizer.step()
                loss_total += loss.item()
            scheduler.step()
            if (epoch + 1) % 10 == 0:
                logger.info(f"  Epoch {epoch+1}/{model_config.TRANSFORMER_EPOCHS} Loss: {loss_total/len(loader):.6f}")
        self._is_trained = True
        logger.info("Transformer 训练完成！")

    def predict(self, X):
        if self.model is None:
            raise ValueError("模型未训练")
        if X.ndim == 2:
            X = X[np.newaxis, :, :]
        if self.scaler_mean is not None:
            X_norm = (X - self.scaler_mean) / self.scaler_std
        else:
            X_norm = X
        self.model.eval()
        with torch.no_grad():
            X_t = torch.FloatTensor(X_norm).permute(0, 2, 1).to(self.device)
            output = self.model(X_t).cpu().numpy()
        last_price = X[:, -1, 0].mean()
        pred = output * (X[:, -1, 0].std() + 1e-8) + last_price
        direction = "up" if pred[0, 0, 1] > last_price else "down"
        confidence = min(abs(pred[0, 0, 1] - last_price) / (pred[0, 0, 2] - pred[0, 0, 0] + 1e-8), 1.0)
        return {
            "prediction_1d": {"low": float(pred[0, 0, 0]), "mid": float(pred[0, 0, 1]), "high": float(pred[0, 0, 2])},
            "prediction_5d": {"low": float(pred[0, -1, 0]), "mid": float(pred[0, -1, 1]), "high": float(pred[0, -1, 2])},
            "direction": direction, "confidence": confidence,
        }

    def save(self, name="transformer_latest.pt"):
        if self.model is None:
            return
        path = MODELS_DIR / name
        torch.save({"model_state": self.model.state_dict(), "scaler_mean": self.scaler_mean,
                     "scaler_std": self.scaler_std}, path)
        logger.info(f"模型已保存: {path}")

    def load(self, name="transformer_latest.pt"):
        path = MODELS_DIR / name
        if not path.exists():
            return False
        checkpoint = torch.load(path, map_location=self.device, weights_only=False)
        self.build_model()
        self.model.load_state_dict(checkpoint["model_state"])
        self.scaler_mean = checkpoint["scaler_mean"]
        self.scaler_std = checkpoint["scaler_std"]
        self._is_trained = True
        return True

    def is_ready(self):
        return self._is_trained and self.model is not None
