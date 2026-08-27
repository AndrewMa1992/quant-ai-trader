"""
PPO reinforcement-learning trading agent.
Built on Stable-Baselines3.

P1-1: Automatic GPU detection (CUDA/MPS/CPU)
P1-2: predict_signal rewrite — mean projection instead of random noise
"""
import numpy as np
import gymnasium as gym
from gymnasium import spaces
from loguru import logger
from configs.settings import settings


class TradingEnv(gym.Env):
    """US-equity trading environment."""

    def __init__(self, df_dict, close_dict=None, feature_dim=40, lookback=60, initial_balance=100000.0,
                 commission=0.001, max_position=0.25):
        super().__init__()
        self.df_dict, self.close_dict, self.feature_dim, self.lookback = df_dict, close_dict, feature_dim, lookback
        self.initial_balance, self.commission = initial_balance, commission
        self.max_position = max_position
        self.tickers = list(df_dict.keys())
        self.n_tickers = len(self.tickers)
        self.max_steps = min(len(v) for v in df_dict.values()) - lookback - 1
        self.state_dim = feature_dim * self.n_tickers + self.n_tickers + 1
        self.action_space = spaces.Box(low=-1, high=1, shape=(self.n_tickers,), dtype=np.float32)
        self.observation_space = spaces.Box(low=-np.inf, high=np.inf, shape=(self.state_dim,), dtype=np.float32)
        self.reset()

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.current_step = self.lookback
        self.balance = self.initial_balance
        self.positions = {t: 0.0 for t in self.tickers}
        self.portfolio_value = self.initial_balance
        self.returns_history = []
        return self._get_state(), {}

    def step(self, actions):
        self.current_step += 1
        done = self.current_step >= self.max_steps - 1
        prices = self._get_prices()
        next_prices = self._get_prices(offset=1)
        if not prices or not next_prices:
            return self._get_state(), 0.0, True, False, {}
        pv_before = self._get_portfolio_value(prices)
        self._execute_trades(actions, prices)
        pv_after = self._get_portfolio_value(next_prices)
        ret = (pv_after - pv_before) / (pv_before + 1e-8)
        self.returns_history.append(ret)
        self.portfolio_value = pv_after
        reward = ret * 100
        if len(self.returns_history) >= 20:
            sharpe = np.mean(self.returns_history[-20:]) / (np.std(self.returns_history[-20:]) + 1e-8) * np.sqrt(252)
            reward += sharpe * 0.1
        return self._get_state(), float(reward), done, False, {}

    def _get_state(self):
        parts = []
        for t in self.tickers:
            data = self.df_dict[t]
            step = min(self.current_step, data.shape[0] - 1)
            parts.append(data[step, :self.feature_dim])
        for t in self.tickers:
            parts.append([self.positions[t]])
        parts.append([self.balance / (self.portfolio_value + 1e-8)])
        return np.clip(np.nan_to_num(np.concatenate(parts).astype(np.float32)), -10, 10)

    def _get_prices(self, offset=0):
        """Current prices, preferring the close-price dictionary."""
        prices = {}
        for t in self.tickers:
            step = min(self.current_step + offset, self.df_dict[t].shape[0] - 1)
            if self.close_dict and t in self.close_dict:
                idx = min(step, len(self.close_dict[t]) - 1)
                p = float(self.close_dict[t][idx])
            else:
                p = float(self.df_dict[t][step, 0])
            prices[t] = max(p, 0.01)  # Keep prices strictly positive
        return prices

    def _get_portfolio_value(self, prices):
        return self.balance + sum(self.positions[t] * prices[t] for t in self.tickers)

    def _execute_trades(self, actions, prices):
        for i, t in enumerate(self.tickers):
            price = prices[t]
            if price <= 0:
                continue
            target = np.clip(actions[i], -self.max_position, self.max_position)
            current = self.positions[t] * price
            trade = target * self.portfolio_value - current
            if abs(trade) < 10:
                continue
            cost = abs(trade) * (self.commission + 0.0005)
            if trade > 0 and cost + trade <= self.balance:
                self.balance -= trade + cost
                self.positions[t] += trade / price
            elif trade < 0:
                shares = min(abs(trade) / price, self.positions[t])
                if shares > 0.001:
                    self.balance += shares * price * (1 - self.commission)
                    self.positions[t] -= shares


# ═══════════════════════════════════════════════════════════════
# P5: Portfolio-level joint action space — portfolio optimization
# ═══════════════════════════════════════════════════════════════
class PortfolioTradingEnv(gym.Env):
    """
    Portfolio-level trading environment — joint action-space optimization.

    Improvements over TradingEnv:
    - Action space: portfolio weight vector (softmax → sum=1)
    - Reward: Sharpe + return - drawdown penalty - turnover cost + diversification
    - State: correlation matrix + macro features
    """

    def __init__(self, df_dict, close_dict=None, feature_dim=40, lookback=60,
                 initial_balance=100000.0, commission=0.001, max_turnover=0.3):
        super().__init__()
        self.df_dict = df_dict
        self.close_dict = close_dict or {}
        self.feature_dim = feature_dim
        self.lookback = lookback
        self.initial_balance = initial_balance
        self.commission = commission
        self.max_turnover = max_turnover
        self.tickers = sorted(df_dict.keys())
        self.n_tickers = len(self.tickers)
        self.max_steps = min(len(v) for v in df_dict.values()) - lookback - 1

        # Action space: target weight per stock in [0, 1]
        self.action_space = spaces.Box(
            low=0, high=1, shape=(self.n_tickers,), dtype=np.float32
        )

        # State space: features + positions + cash + corr matrix (upper triangle)
        n_corr_features = self.n_tickers * (self.n_tickers - 1) // 2
        self.state_dim = (feature_dim * self.n_tickers
                          + self.n_tickers      # Current positions
                          + 1                   # Cash ratio
                          + min(n_corr_features, 20))  # Correlation (truncated)
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(self.state_dim,), dtype=np.float32
        )
        self.reset()

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.current_step = self.lookback
        self.balance = self.initial_balance
        self.positions = {t: 0.0 for t in self.tickers}
        self.prev_weights = np.zeros(self.n_tickers)
        self.portfolio_value = self.initial_balance
        self.returns_history = []
        self.peak_value = self.initial_balance
        return self._get_state(), {}

    def step(self, actions):
        self.current_step += 1
        done = self.current_step >= self.max_steps - 1

        prices = self._get_prices()
        next_prices = self._get_prices(offset=1)
        if not prices or not next_prices:
            return self._get_state(), 0.0, True, False, {}

        # Actions → target weights (softmax so they sum to 1)
        target_weights = self._actions_to_weights(actions, prices)

        pv_before = self._get_portfolio_value(prices)
        self._execute_rebalance(target_weights, prices)
        pv_after = self._get_portfolio_value(next_prices)

        # Update peak
        if pv_after > self.peak_value:
            self.peak_value = pv_after

        ret = (pv_after - pv_before) / (pv_before + 1e-8)
        self.returns_history.append(ret)
        self.portfolio_value = pv_after
        self.prev_weights = target_weights

        # === Portfolio-level reward ===
        reward = self._compute_reward(ret, target_weights, actions)
        return self._get_state(), float(reward), done, False, {}

    def _compute_reward(self, ret, weights, raw_actions):
        """Portfolio-level multi-factor reward."""
        reward = 0.0

        # 1. Base return (×100 scale)
        reward += ret * 100

        # 2. Sharpe bonus (20-day rolling)
        if len(self.returns_history) >= 5:
            recent = self.returns_history[-min(20, len(self.returns_history)):]
            sharpe = np.mean(recent) / (np.std(recent) + 1e-8) * np.sqrt(252)
            reward += max(sharpe, -3) * 0.15

        # 3. Max-drawdown penalty
        dd = (self.peak_value - self.portfolio_value) / (self.peak_value + 1e-8)
        reward -= dd * 0.5

        # 4. Turnover cost
        turnover = np.sum(np.abs(weights - self.prev_weights))
        reward -= turnover * 0.02

        # 5. Diversification bonus (weights not concentrated in one name)
        hhi = np.sum(weights ** 2)  # Herfindahl index
        diversification = 1.0 - (hhi * self.n_tickers - 1) / (self.n_tickers - 1)
        reward += max(0, diversification) * 0.05

        return float(np.clip(reward, -10, 10))

    def _actions_to_weights(self, actions, prices) -> np.ndarray:
        """Convert an action vector into portfolio weights."""
        # Softmax normalize
        actions = np.clip(np.nan_to_num(actions), -5, 5)
        exp_actions = np.exp(actions - np.max(actions))
        weights = exp_actions / (exp_actions.sum() + 1e-8)

        # Keep a cash buffer
        max_total = 0.95
        if weights.sum() > max_total:
            weights = weights / weights.sum() * max_total

        return weights

    def _execute_rebalance(self, target_weights, prices):
        """Execute a portfolio rebalance."""
        total_value = self._get_portfolio_value(prices)
        cash_target = (1.0 - target_weights.sum()) * total_value

        for i, t in enumerate(self.tickers):
            price = prices.get(t, 0)
            if price <= 0:
                continue
            target_value = target_weights[i] * total_value
            current_value = self.positions[t] * price
            trade_value = target_value - current_value

            if abs(trade_value) < 10:
                continue

            cost = abs(trade_value) * self.commission
            if trade_value > 0:
                if trade_value + cost <= self.balance:
                    self.balance -= trade_value + cost
                    self.positions[t] += trade_value / price
            else:
                shares = min(abs(trade_value) / price, self.positions[t])
                if shares > 0.001:
                    self.balance += shares * price * (1 - self.commission)
                    self.positions[t] -= shares

    def _get_state(self):
        """Build an augmented state vector (including correlation features)."""
        parts = []
        for t in self.tickers:
            data = self.df_dict[t]
            step = min(self.current_step, data.shape[0] - 1)
            features = data[step, :self.feature_dim]
            parts.append(np.nan_to_num(features))

        for t in self.tickers:
            parts.append([self.positions[t]])

        parts.append([self.balance / (self.portfolio_value + 1e-8)])

        # Correlation features (truncate to 20 dims)
        corr_features = self._compute_correlation_features()
        parts.append(corr_features[:20])

        return np.clip(np.nan_to_num(np.concatenate(parts).astype(np.float32)), -10, 10)

    def _compute_correlation_features(self) -> np.ndarray:
        """Compute pairwise correlation features."""
        returns_list = []
        for t in self.tickers:
            data = self.df_dict[t]
            step = min(self.current_step, data.shape[0] - 1)
            if step >= self.lookback:
                prices = data[step - self.lookback:step, 0]
                if len(prices) >= 5:
                    rets = np.diff(prices) / (prices[:-1] + 1e-8)
                    returns_list.append(rets)

        if len(returns_list) < 2:
            return np.zeros(20)

        min_len = min(len(r) for r in returns_list)
        if min_len < 3:
            return np.zeros(20)

        aligned = np.array([r[:min_len] for r in returns_list])
        try:
            corr = np.corrcoef(aligned)
            upper_tri = corr[np.triu_indices_from(corr, k=1)]
            return np.nan_to_num(upper_tri)
        except Exception:
            return np.zeros(20)

    def _get_prices(self, offset=0):
        prices = {}
        for t in self.tickers:
            step = min(self.current_step + offset, self.df_dict[t].shape[0] - 1)
            if self.close_dict and t in self.close_dict:
                idx = min(step, len(self.close_dict[t]) - 1)
                p = float(self.close_dict[t][idx])
            else:
                p = float(self.df_dict[t][step, 0])
            prices[t] = max(p, 0.01)
        return prices

    def _get_portfolio_value(self, prices):
        return self.balance + sum(self.positions[t] * prices.get(t, 0) for t in self.tickers)


class TradingRLAgent:
    """PPO reinforcement-learning trading agent."""

    def __init__(self):
        self.model = None
        self.env = None
        self._is_trained = False
        self._device: str = self._detect_device()

    @staticmethod
    def _detect_device() -> str:
        """
        P1-1: Auto-detect the available device.
        Priority: CUDA > MPS (Apple Silicon) > CPU

        Returns:
            'cuda', 'mps', or 'cpu'
        """
        try:
            import torch
            if torch.cuda.is_available():
                device = "cuda"
                logger.info(f"🖥️ GPU detect: CUDA — {torch.cuda.get_device_name(0)}")
            elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                device = "mps"
                logger.info("🖥️ GPU detect: Apple MPS (Metal Performance Shaders)")
            else:
                device = "cpu"
                logger.info("🖥️ GPU detect: CPU only")
            return device
        except ImportError:
            logger.warning("⚠️ PyTorch not installed; using CPU")
            return "cpu"

    def create_env(self, df_dict, close_dict=None, feature_dim=40, lookback=60, initial_balance=100000.0):
        self.env = TradingEnv(df_dict, close_dict, feature_dim, lookback, initial_balance,
                              max_position=settings.MODEL_RL_MAX_TRADE_PERCENT)
        return self.env

    def build_model(self):
        """P1-1: Build the PPO model; auto-detect GPU."""
        from stable_baselines3 import PPO
        if self.env is None:
            raise ValueError("Create an environment first")
        self.model = PPO("MlpPolicy", self.env, learning_rate=settings.MODEL_RL_LEARNING_RATE,
                         n_steps=settings.MODEL_RL_N_STEPS, batch_size=settings.MODEL_RL_BATCH_SIZE,
                         gamma=settings.MODEL_RL_GAMMA, verbose=0, device=self._device,
                         ent_coef=settings.MODEL_RL_ENT_COEF,
                         clip_range=settings.MODEL_RL_CLIP_RANGE)
        logger.info(f"PPO model built (device={self._device}, ent_coef={settings.MODEL_RL_ENT_COEF}, "
                    f"clip_range={settings.MODEL_RL_CLIP_RANGE})")
        return self.model

    def train(self, total_timesteps=None):
        if self.model is None:
            self.build_model()
        timesteps = total_timesteps or settings.MODEL_RL_TOTAL_TIMESTEPS
        logger.info(f"PPO training started: {timesteps:,} timesteps (device={self._device})")
        self.model.learn(total_timesteps=timesteps, progress_bar=True)
        self._is_trained = True
        logger.info("PPO training complete.")

    def predict(self, state, deterministic=True):
        if self.model is None:
            raise ValueError("Model is not trained")
        return self.model.predict(state, deterministic=deterministic)

    def save(self, name="ppo_trader.zip"):
        if self.model is None:
            return
        self.model.save(str(MODELS_DIR / name))
        logger.info("PPO saved")

    def load(self, name="ppo_trader.zip"):
        """P1-1: Load the model onto the auto-detected device."""
        from stable_baselines3 import PPO
        import os as _os
        path = str(MODELS_DIR / name)
        if not _os.path.exists(path):
            logger.warning(f"Model file not found: {path}")
            return False
        self.model = PPO.load(path, device=self._device)
        self._is_trained = True
        logger.info(f"PPO model loaded (device={self._device})")
        return True

    def is_ready(self):
        return self._is_trained

    def predict_signal(
        self,
        features: np.ndarray,
        ticker: str = "",
        price: float = 0.0,
        position_pct: float = 0.0,
    ) -> dict:
        """Single-ticker inference for a multi-ticker PPO policy.

        Only the first ticker slot is filled with real features; remaining
        slots are zero (not mean-cloned). Confidence is haircut when the
        policy was trained with many more names than one.
        """
        if not self._is_trained or features.shape[0] < 30:
            return {"signal": "neutral", "strength": 0.0, "confidence": 0.0}

        try:
            obs_shape = self.model.observation_space.shape[0]
            n_features = min(features.shape[1], 37)

            recent = features[-20:]
            feat_last = recent[-1, :n_features].astype(np.float64)

            # obs = [feat_t0..feat_tn] + [pos_t0..pos_tn] + [cash]
            n_virtual = max(1, (obs_shape - 1) // (n_features + 1))

            state_parts = []
            for i in range(n_virtual):
                if i == 0:
                    state_parts.append(feat_last)
                else:
                    state_parts.append(np.zeros(n_features, dtype=np.float64))

            for i in range(n_virtual):
                state_parts.append(np.array([position_pct if i == 0 else 0.0]))

            state_parts.append(np.array([1.0 - position_pct]))

            state = np.nan_to_num(np.concatenate(state_parts).astype(np.float32))
            if len(state) < obs_shape:
                state = np.pad(state, (0, obs_shape - len(state)), mode="constant")
            elif len(state) > obs_shape:
                state = state[:obs_shape]
            state = np.clip(state, -10, 10)

            action, _states = self.model.predict(state, deterministic=True)

            if isinstance(action, np.ndarray):
                # Prefer first ticker action if vector-valued
                action_val = float(action.ravel()[0])
            else:
                action_val = float(action)

            if action_val > 0.05:
                signal = "buy"
                strength = min(abs(action_val) * 2.0, 1.0)
            elif action_val < -0.05:
                signal = "sell"
                strength = min(abs(action_val) * 2.0, 1.0)
            else:
                signal = "hold"
                strength = 0.0

            confidence = min(abs(action_val) * 1.5 + 0.3, 1.0)
            # Haircut when policy is multi-name and we only filled one slot
            if n_virtual > 1:
                confidence *= max(0.35, 1.0 / np.sqrt(n_virtual))

            return {
                "signal": signal,
                "strength": float(strength),
                "confidence": float(np.clip(confidence, 0.0, 1.0)),
                "single_ticker_mode": True,
                "n_virtual_slots": n_virtual,
                "ticker": ticker,
            }
        except Exception as e:
            logger.warning(f"RL predict_signal failed for {ticker}: {e}")
            return {"signal": "neutral", "strength": 0.0, "confidence": 0.0}

    def predict_portfolio(
        self,
        tickers: list,
        features_dict: dict,
        prices_dict: dict = None,
        positions_dict: dict = None,
    ) -> list:
        """
        P5: Portfolio-level joint inference — optimized weights for the whole book.
        """
        if not self._is_trained or len(tickers) < 2:
            return [{"ticker": t, "signal": "neutral", "strength": 0.0,
                     "confidence": 0.0, "target_weight": 0.0} for t in tickers]

        try:
            obs_shape = self.model.observation_space.shape[0]
            n_features = 37

            state_parts = []
            for t in tickers:
                features = features_dict.get(t)
                if features is not None and features.shape[0] >= 20:
                    feat_last = features[-1, :min(features.shape[1], n_features)]
                    feat_last = np.nan_to_num(feat_last)
                else:
                    feat_last = np.zeros(min(n_features, max(1, obs_shape // (len(tickers) + 1))))
                state_parts.append(feat_last.astype(np.float64))

            for t in tickers:
                pos = positions_dict.get(t, 0.0) if positions_dict else 0.0
                state_parts.append(np.array([pos]))

            state_parts.append(np.array([0.8]))

            state = np.nan_to_num(np.concatenate(state_parts).astype(np.float32))
            if len(state) < obs_shape:
                state = np.pad(state, (0, obs_shape - len(state)), mode='constant')
            elif len(state) > obs_shape:
                state = state[:obs_shape]
            state = np.clip(state, -10, 10)

            actions, _states = self.model.predict(state, deterministic=True)

            if isinstance(actions, np.ndarray) and len(actions) == len(tickers):
                raw_actions = actions
            else:
                action_val = float(np.mean(actions)) if isinstance(actions, np.ndarray) else float(actions)
                raw_actions = np.full(len(tickers), action_val)

            exp_act = np.exp(np.clip(raw_actions, -5, 5) - np.max(np.clip(raw_actions, -5, 5)))
            weights = exp_act / (exp_act.sum() + 1e-8)

            results = []
            weight_threshold = 1.0 / len(tickers)
            for i, ticker in enumerate(tickers):
                w = float(weights[i])
                if w > weight_threshold * 1.5:
                    signal, strength = "buy", min(w / (weight_threshold * 3), 1.0)
                    confidence = min(w * 3, 0.8)
                elif w < weight_threshold * 0.3:
                    signal, strength = "sell", min((weight_threshold - w) / weight_threshold, 1.0)
                    confidence = min((1 - w / weight_threshold) * 0.5, 0.7)
                else:
                    signal, strength, confidence = "neutral", w / weight_threshold, 0.3

                results.append({
                    "ticker": ticker, "signal": signal, "strength": strength,
                    "confidence": confidence, "target_weight": w,
                    "rl_action": float(raw_actions[i]) if i < len(raw_actions) else 0.0,
                })

            return results

        except Exception as e:
            logger.debug(f"Portfolio RL inference failed: {e}")
            return [{"ticker": t, "signal": "neutral", "strength": 0.0,
                     "confidence": 0.0, "target_weight": 0.0} for t in tickers]
