"""services/model_train_service/trainers/rl_trainer.py – Reinforcement Learning trainer.

PPO + SAC via Stable-Baselines3 + custom TradingEnv.
Obs: price history + factor values + position state.
Action: {0: hold, 1: buy, 2: sell}.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd
from loguru import logger

from services.model_train_service.config import train_config
from services.model_train_service.trainers.trainer_base import TrainerBase

# Try importing gym and SB3 at module level for graceful fallback
try:
    import gymnasium as gym
    from gymnasium import spaces

    HAS_GYM = True
except ImportError:
    HAS_GYM = False
    gym: Any = None  # type: ignore[no-redef]
    spaces: Any = None  # type: ignore[no-redef]

try:
    from stable_baselines3 import PPO, SAC

    HAS_SB3 = True
except ImportError:
    HAS_SB3 = False
    PPO: Any = None  # type: ignore[no-redef]
    SAC: Any = None  # type: ignore[no-redef]


class TradingEnv(gym.Env if HAS_GYM else object):
    """Gymnasium trading environment for RL agent training.

    Obs: last `window` bars of [price_ret, volume_ratio, factor_vals, position].
    Action: 0=hold, 1=buy, 2=sell.
    Reward: daily PnL change with penalty for churn.
    """

    metadata = {"render_modes": ["human"]}

    def __init__(
        self,
        data: np.ndarray,
        window: int = 20,
        initial_cash: float = 1_000_000.0,
        commission: float = 0.0005,
    ) -> None:
        super().__init__()
        if not HAS_GYM:
            raise ImportError("gymnasium is required for RL training")

        self.data = data.astype(np.float32)  # (n_steps, n_features)
        self.window = window
        self.initial_cash = initial_cash
        self.commission = commission
        self.n_steps = len(data)
        self.n_features = data.shape[1]

        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf,
            shape=(window, self.n_features + 1),  # +1 for position
            dtype=np.float32,
        )
        self.action_space = spaces.Discrete(3)  # 0=hold, 1=buy, 2=sell

        self.reset()

    def reset(
        self, seed: int | None = None, options: dict | None = None
    ) -> tuple[np.ndarray, dict]:
        super().reset(seed=seed)
        self.current_step = self.window
        self.position = 0  # -1=short, 0=flat, 1=long
        self.cash = self.initial_cash
        self.portfolio_value = self.initial_cash
        obs = self._get_obs()
        return obs, {}

    def step(self, action: int) -> tuple[np.ndarray, float, bool, bool, dict]:
        prev_value = self.portfolio_value

        # Execute action
        if action == 1 and self.position <= 0:  # Buy
            self.position = 1
        elif action == 2 and self.position >= 0:  # Sell
            self.position = -1

        # Price movement
        price_change = self.data[self.current_step, 0]  # First column = price return
        self.portfolio_value = self.cash + self.position * self.portfolio_value * price_change

        reward = self.portfolio_value - prev_value
        # Penalize excessive trading
        if action != 0:
            reward -= self.commission * self.portfolio_value

        self.current_step += 1
        terminated = self.current_step >= self.n_steps - 1
        truncated = False

        return self._get_obs(), float(reward), terminated, truncated, {"portfolio_value": self.portfolio_value}

    def _get_obs(self) -> np.ndarray:
        """Build observation window."""
        start = self.current_step - self.window
        obs_data = self.data[start:self.current_step, :]

        # Pad if needed
        if obs_data.shape[0] < self.window:
            pad = np.zeros((self.window - obs_data.shape[0], self.n_features), dtype=np.float32)
            obs_data = np.vstack([pad, obs_data])

        # Add position channel
        pos_col = np.full((self.window, 1), float(self.position), dtype=np.float32)
        return np.hstack([obs_data, pos_col])


class RLTrainer(TrainerBase):
    """RL trainer using Stable-Baselines3 PPO or SAC.

    Trains on a single-asset TradingEnv with factor+price observations.
    """

    model_name = "rl"

    def __init__(
        self,
        algo: str = "PPO",
        device: str | None = None,
    ) -> None:
        super().__init__(device=device or train_config.DEVICE)
        self.algo = algo.upper()

    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        X_valid: pd.DataFrame | None = None,
        y_valid: pd.Series | None = None,
        **kwargs: Any,
    ) -> dict[str, float]:
        """Train RL agent on trading environment.

        Args:
            X: Features (price returns should be in first column).
            y: Target (used for env reward computation indirectly).
            X_valid: Not used for RL.
            y_valid: Not used for RL.
            **kwargs: rl_timesteps.

        Returns:
            Training metrics.
        """
        if not HAS_GYM or not HAS_SB3:
            logger.warning("gymnasium/stable-baselines3 not available — using mock training")
            self.model = {"algo": self.algo, "trained": False}
            return {"train_reward": 0.0, "mean_reward": 0.0}

        self._validate_data(X, y)
        self._feature_names = list(X.columns)

        data = np.column_stack([y.values, X.values])  # First column = returns
        env = TradingEnv(data=data, window=20)

        total_timesteps = kwargs.get("rl_timesteps", train_config.RL_TIMESTEPS)

        if self.algo == "SAC":
            self.model = SAC("MlpPolicy", env, verbose=0, device=self.device)
        else:
            self.model = PPO("MlpPolicy", env, verbose=0, device=self.device)

        self.model.learn(total_timesteps=total_timesteps)

        # Evaluate
        obs, _ = env.reset()
        total_reward = 0.0
        n_steps = 0
        for _ in range(min(100, data.shape[0] - 20)):
            action, _ = self.model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, _ = env.step(int(action))
            total_reward += float(reward)
            n_steps += 1
            if terminated or truncated:
                break

        mean_reward = total_reward / max(n_steps, 1)
        logger.info(f"RL ({self.algo}) training complete: mean_reward={mean_reward:.4f}")

        return {"train_reward": round(float(total_reward), 4), "mean_reward": round(mean_reward, 4),
                "timesteps": total_timesteps}

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Generate RL actions.

        Returns:
            Action array with values in [-1, 1] (hold=0, buy>0, sell<0).
        """
        if self.model is None:
            raise RuntimeError("Model not trained")

        if not HAS_SB3 or isinstance(self.model, dict):
            # Mock: random signals
            return np.random.uniform(-0.3, 0.3, len(X))

        data = X.values.astype(np.float32)
        env = TradingEnv(data=data, window=min(20, len(data) - 1))

        actions = []
        obs, _ = env.reset()
        for _ in range(len(data) - 20):
            action, _ = self.model.predict(obs, deterministic=True)
            obs, _, _, _, _ = env.step(int(action))
            # Map: 0→0, 1→0.5, 2→-0.5
            act_val = {0: 0.0, 1: 0.5, 2: -0.5}[int(action)]
            actions.append(act_val)

        padded = np.zeros(len(X))
        padded[:len(actions)] = actions
        return padded

    def get_action_probs(self, X: pd.DataFrame) -> dict[str, np.ndarray]:
        """Return action probabilities.

        Returns:
            Dict with 'hold', 'buy', 'sell' arrays.
        """
        if not HAS_SB3 or isinstance(self.model, dict):
            n = len(X)
            return {"hold": np.full(n, 0.5), "buy": np.full(n, 0.25), "sell": np.full(n, 0.25)}

        data = X.values.astype(np.float32)
        env = TradingEnv(data=data, window=min(20, len(data) - 1))
        n = min(len(data) - 20, len(X))
        probs = {"hold": np.zeros(n), "buy": np.zeros(n), "sell": np.zeros(n)}

        obs, _ = env.reset()
        for i in range(n):
            action_probs = self.model.policy.predict(obs, deterministic=False)
            if hasattr(action_probs, "__getitem__"):
                probs["hold"][i] = float(action_probs[0][0]) if hasattr(action_probs[0], "__getitem__") else 0.5
                probs["buy"][i] = float(action_probs[0][1]) if hasattr(action_probs[0], "__getitem__") and len(action_probs[0]) > 1 else 0.25
                probs["sell"][i] = float(action_probs[0][2]) if hasattr(action_probs[0], "__getitem__") and len(action_probs[0]) > 2 else 0.25
            obs, _, _, _, _ = env.step(int(self.model.predict(obs, deterministic=True)[0]))

        return probs

    def save(self, path: str) -> None:
        import os
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if HAS_SB3 and not isinstance(self.model, dict):
            self.model.save(path)
        else:
            import joblib
            joblib.dump({"algo": self.algo, "mock": True}, path)
        logger.info(f"RL model saved to {path}")

    def load(self, path: str) -> None:
        import os
        if os.path.exists(path) and HAS_SB3:
            import joblib
            data = joblib.load(path)
            if isinstance(data, dict) and data.get("mock"):
                self.model = data
            elif HAS_SB3:
                if self.algo == "SAC":
                    self.model = SAC.load(path, device=self.device)
                else:
                    self.model = PPO.load(path, device=self.device)
        logger.info(f"RL model loaded from {path}")
