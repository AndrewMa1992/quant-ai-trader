"""services/model_infer_service/models/rl_model.py – RL inference wrapper.

Builds observations matching ``TradingEnv`` (window × features+position).
Never injects random noise into live signals — unloaded/errors → zeros.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from services.model_infer_service.config import infer_config
from services.model_infer_service.models.preprocess import align_features
from services.model_train_service.trainers.rl_actions import apply_position


class RLInference:
    """RL inference wrapper for action prediction."""

    model_name = "rl"
    DEFAULT_WINDOW = 20

    def __init__(self, device: str | None = None) -> None:
        self.model: Any = None
        self.device = device or infer_config.DEVICE
        self.loaded = False
        self._algo: str = "PPO"
        self._window: int = self.DEFAULT_WINDOW
        self._feature_names: list[str] = []
        self._n_features: int | None = None
        self.last_missing_fraction: float = 0.0

    def load(self, path: str) -> bool:
        """Load RL model + optional ``{path}.meta.json`` sidecar."""
        try:
            self._load_meta(path)

            if path.lower().endswith(".zip"):
                return self._load_sb3(path)

            data = self._safe_deserialize(path)
            if data is None:
                logger.warning(f"RL model deserialization failed for {path}")
                self.loaded = False
                return False

            if isinstance(data, dict) and data.get("mock"):
                self.model = data
                self.loaded = False
                return False

            # Sidecar metadata may be embedded
            if isinstance(data, dict):
                if data.get("feature_names"):
                    self._feature_names = list(data["feature_names"])
                if data.get("window"):
                    self._window = int(data["window"])
                if data.get("n_features"):
                    self._n_features = int(data["n_features"])

            return self._load_sb3(path)
        except Exception as e:
            logger.error(f"Failed to load RL model: {e}")
            self.loaded = False
            return False

    def _load_meta(self, path: str) -> None:
        meta_path = Path(str(path) + ".meta.json")
        if not meta_path.exists():
            # Also try stripping .zip
            alt = Path(str(path).removesuffix(".zip") + ".meta.json")
            meta_path = alt if alt.exists() else meta_path
        if not meta_path.exists():
            return
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            self._window = int(meta.get("window", self._window))
            self._feature_names = list(meta.get("feature_names") or [])
            if meta.get("n_features") is not None:
                self._n_features = int(meta["n_features"])
            self._algo = str(meta.get("algo", self._algo)).upper()
        except Exception as exc:
            logger.debug(f"RL meta load skipped: {exc}")

    def _load_sb3(self, path: str) -> bool:
        try:
            from stable_baselines3 import PPO, SAC
        except ImportError:
            logger.warning("stable-baselines3 not installed")
            self.loaded = False
            return False

        try:
            if "sac" in path.lower() or self._algo == "SAC":
                # SAC requires continuous actions — v2 env is Discrete → refuse
                logger.warning(
                    "SAC checkpoint incompatible with Discrete(3) TradingEnv; "
                    "refusing load (retrain with PPO)"
                )
                self.loaded = False
                return False
            self.model = PPO.load(path, device=self.device)
            self._algo = "PPO"
            self.loaded = True
            logger.info(f"RL model (PPO) loaded from {path} window={self._window}")
            return True
        except Exception as e:
            logger.error(f"SB3 load failed: {e}")
            self.loaded = False
            return False

    @staticmethod
    def _safe_deserialize(path: str) -> Any:
        try:
            import joblib
            return joblib.load(path)
        except Exception as e:
            logger.debug(f"joblib.load failed for {path}: {e}")
        try:
            import pickle
            with open(path, "rb") as f:
                return pickle.load(f)
        except Exception as e:
            logger.debug(f"pickle.load failed for {path}: {e}")
        try:
            import torch
            return torch.load(path, map_location="cpu", weights_only=False)
        except Exception as e:
            logger.debug(f"torch.load failed for {path}: {e}")
        return None

    def _build_env_data(self, X: pd.DataFrame) -> np.ndarray:
        """Match training: ``column_stack([returns, features])``."""
        aligned, miss = align_features(X, self._feature_names or list(X.columns))
        self.last_missing_fraction = miss
        feat = np.nan_to_num(aligned.values.astype(np.float32), nan=0.0, posinf=1.0, neginf=-1.0)

        # Prefer ret_1d as the leading return channel used in reward/obs
        if "ret_1d" in aligned.columns:
            ret = aligned["ret_1d"].values.astype(np.float32)
        else:
            ret = feat[:, 0].astype(np.float32)
        ret = np.nan_to_num(ret, nan=0.0, posinf=1.0, neginf=-1.0)
        return np.column_stack([ret, feat]).astype(np.float32)

    def _obs_from_window(self, data: np.ndarray, end: int, position: float = 0.0) -> np.ndarray:
        """Build one TradingEnv-compatible observation."""
        window = self._window
        start = end - window
        obs_data = data[max(0, start):end].copy()
        obs_data = np.nan_to_num(obs_data, nan=0.0, posinf=1.0, neginf=-1.0)
        n_feat = data.shape[1]
        if obs_data.shape[0] < window:
            pad = np.zeros((window - obs_data.shape[0], n_feat), dtype=np.float32)
            obs_data = np.vstack([pad, obs_data])
        pos_col = np.full((window, 1), float(position), dtype=np.float32)
        return np.hstack([obs_data, pos_col]).astype(np.float32)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Predict actions as values ∈ [-1, 1]. Unloaded → zeros (no noise)."""
        n = len(X)
        if not self.loaded or self.model is None:
            return np.zeros(n, dtype=np.float64)

        try:
            data = self._build_env_data(X)
            if len(data) <= self._window:
                return np.zeros(n)

            action_map = {0: 0.0, 1: 0.5, 2: -0.5}
            out = np.zeros(n, dtype=np.float64)
            position = 0.0

            # Roll through history so the last step matches live state
            for i in range(self._window, len(data)):
                obs = self._obs_from_window(data, i, position=position)
                action, _ = self.model.predict(obs, deterministic=True)
                a = int(action) if not hasattr(action, "__len__") else int(np.asarray(action).ravel()[0])
                out[i] = action_map.get(a, 0.0)
                position = apply_position(position, a)

            return out
        except Exception as e:
            logger.error(f"RL prediction error: {e}")
            return np.zeros(n, dtype=np.float64)

    def get_action_probs(self, X: pd.DataFrame) -> dict[str, np.ndarray]:
        """Get one-hot action indicators (deterministic policy)."""
        n = len(X)
        neutral = {
            "hold_prob": np.full(n, 1.0),
            "buy_prob": np.zeros(n),
            "sell_prob": np.zeros(n),
        }
        if not self.loaded or self.model is None:
            return neutral

        try:
            actions = self.predict(X)
            hold = (actions == 0.0).astype(np.float64)
            buy = (actions > 0).astype(np.float64)
            sell = (actions < 0).astype(np.float64)
            return {"hold_prob": hold, "buy_prob": buy, "sell_prob": sell}
        except Exception:
            return neutral
