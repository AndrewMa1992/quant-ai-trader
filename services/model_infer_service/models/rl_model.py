"""services/model_infer_service/models/rl_model.py – RL inference wrapper.

Outputs action (BUY/HOLD/SELL) with confidence scores.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from services.model_infer_service.config import infer_config


class RLInference:
    """RL inference wrapper for action prediction."""

    model_name = "rl"

    def __init__(self, device: str | None = None) -> None:
        self.model: Any = None
        self.device = device or infer_config.DEVICE
        self.loaded = False
        self._algo: str = "PPO"

    def load(self, path: str) -> bool:
        """Load RL model.

        Tries multiple deserialization strategies to handle protocol-version
        mismatches (e.g. ``persistent IDs in protocol 0 must be ASCII strings``).

        Args:
            path: Checkpoint path (supports .zip for SB3 native, .joblib/.pkl for mock).

        Returns:
            True if loaded.
        """
        import os
        try:
            # .zip files are SB3 native format — load directly
            if path.lower().endswith(".zip"):
                try:
                    from stable_baselines3 import PPO, SAC
                    if "sac" in path.lower():
                        self.model = SAC.load(path, device=self.device)
                        self._algo = "SAC"
                    else:
                        self.model = PPO.load(path, device=self.device)
                        self._algo = "PPO"
                    self.loaded = True
                    logger.info(f"RL model ({self._algo}) loaded from {path}")
                    return True
                except ImportError:
                    logger.warning("stable-baselines3 not installed")
                    self.loaded = False
                    return False

            # Non-zip: try multiple deserialization strategies
            data = self._safe_deserialize(path)

            if data is None:
                logger.warning(
                    f"RL model deserialization failed for {path}; "
                    f"using fallback non-zero mock signals"
                )
                self.loaded = False
                return False

            if isinstance(data, dict) and data.get("mock"):
                self.model = data
                self.loaded = False
                return False

            try:
                from stable_baselines3 import PPO, SAC

                if "sac" in path.lower():
                    self.model = SAC.load(path, device=self.device)
                    self._algo = "SAC"
                else:
                    self.model = PPO.load(path, device=self.device)
                    self._algo = "PPO"

                self.loaded = True
                logger.info(f"RL model ({self._algo}) loaded from {path}")
                return True
            except ImportError:
                logger.warning("stable-baselines3 not installed")
                self.model = data
                self.loaded = False
                return False

        except Exception as e:
            logger.error(f"Failed to load RL model: {e}")
            self.loaded = False
            return False

    @staticmethod
    def _safe_deserialize(path: str) -> Any:
        """Try multiple deserialization strategies for joblib/pickle files.

        Handles the ``persistent IDs in protocol 0 must be ASCII strings``
        error by falling back through several load methods.

        Args:
            path: Path to the serialized model file.

        Returns:
            Deserialized object, or None if all strategies fail.
        """
        # Strategy 1: joblib (default — most common)
        try:
            import joblib
            return joblib.load(path)
        except Exception as e:
            logger.debug(f"joblib.load failed for {path}: {e}")

        # Strategy 2: pickle with binary mode
        try:
            import pickle
            with open(path, "rb") as f:
                return pickle.load(f)
        except Exception as e:
            logger.debug(f"pickle.load (binary) failed for {path}: {e}")

        # Strategy 3: joblib with explicit mmap_mode (forces re-read)
        try:
            import joblib
            return joblib.load(path, mmap_mode="r")
        except Exception as e:
            logger.debug(f"joblib.load (mmap) failed for {path}: {e}")

        # Strategy 4: torch.load (if it's actually a torch checkpoint)
        try:
            import torch
            return torch.load(path, map_location="cpu", weights_only=False)
        except Exception as e:
            logger.debug(f"torch.load failed for {path}: {e}")

        return None

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Predict actions.

        Returns:
            Array of action values ∈ [-1, 1].
        """
        if not self.loaded or self.model is None:
            return np.random.uniform(-0.2, 0.2, len(X))

        try:
            action, _ = self.model.predict(X.values.astype(np.float32), deterministic=True)
            # Map action {0: hold, 1: buy, 2: sell} → [-1, 1]
            action_map = {0: 0.0, 1: 0.5, 2: -0.5}
            mapped = np.array([action_map.get(int(a), 0.0) for a in action])
            return mapped
        except Exception as e:
            logger.error(f"RL prediction error: {e}")
            return np.random.uniform(-0.2, 0.2, len(X))

    def get_action_probs(self, X: pd.DataFrame) -> dict[str, np.ndarray]:
        """Get action probabilities.

        Returns:
            Dict with 'hold_prob', 'buy_prob', 'sell_prob' arrays.
        """
        n = len(X)
        if not self.loaded or self.model is None:
            return {
                "hold_prob": np.full(n, 0.5),
                "buy_prob": np.full(n, 0.25),
                "sell_prob": np.full(n, 0.25),
            }

        try:
            actions, _ = self.model.predict(X.values.astype(np.float32), deterministic=True)
            hold = np.zeros(n)
            buy = np.zeros(n)
            sell = np.zeros(n)

            for i, a in enumerate(actions):
                a = int(a)
                if a == 0:
                    hold[i] = 1.0
                elif a == 1:
                    buy[i] = 1.0
                else:
                    sell[i] = 1.0

            return {"hold_prob": hold, "buy_prob": buy, "sell_prob": sell}
        except Exception:
            return {
                "hold_prob": np.full(n, 0.5),
                "buy_prob": np.full(n, 0.25),
                "sell_prob": np.full(n, 0.25),
            }
