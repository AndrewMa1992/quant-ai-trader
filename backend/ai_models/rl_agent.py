"""
PPO 强化学习交易智能体
基于 Stable-Baselines3
"""
from typing import Dict, List, Tuple, Any
import numpy as np
import gymnasium as gym
from gymnasium import spaces
from loguru import logger
from backend.config import model_config, MODELS_DIR


class TradingEnv(gym.Env):
    """美股交易环境"""

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
        """获取当前价格，优先使用收盘价字典"""
        prices = {}
        for t in self.tickers:
            step = min(self.current_step + offset, self.df_dict[t].shape[0] - 1)
            if self.close_dict and t in self.close_dict:
                idx = min(step, len(self.close_dict[t]) - 1)
                p = float(self.close_dict[t][idx])
            else:
                p = float(self.df_dict[t][step, 0])
            prices[t] = max(p, 0.01)  # 确保价格为正
        return prices

    def _get_portfolio_value(self, prices):
        return self.balance + sum(self.positions[t] * prices[t] for t in self.tickers)

    def _execute_trades(self, actions, prices):
        for i, t in enumerate(self.tickers):
            price = prices[t]
            if price <= 0: continue
            target = np.clip(actions[i], -self.max_position, self.max_position)
            current = self.positions[t] * price
            trade = target * self.portfolio_value - current
            if abs(trade) < 10: continue
            cost = abs(trade) * (self.commission + 0.0005)
            if trade > 0 and cost + trade <= self.balance:
                self.balance -= trade + cost
                self.positions[t] += trade / price
            elif trade < 0:
                shares = min(abs(trade) / price, self.positions[t])
                if shares > 0.001:
                    self.balance += shares * price * (1 - self.commission)
                    self.positions[t] -= shares


class TradingRLAgent:
    def __init__(self):
        self.model = None
        self.env = None
        self._is_trained = False

    def create_env(self, df_dict, close_dict=None, feature_dim=40, lookback=60, initial_balance=100000.0):
        self.env = TradingEnv(df_dict, close_dict, feature_dim, lookback, initial_balance,
                              max_position=model_config.RL_MAX_TRADE_PERCENT)
        return self.env

    def build_model(self):
        from stable_baselines3 import PPO
        if self.env is None:
            raise ValueError("请先创建环境")
        self.model = PPO("MlpPolicy", self.env, learning_rate=model_config.RL_LEARNING_RATE,
                         n_steps=model_config.RL_N_STEPS, batch_size=model_config.RL_BATCH_SIZE,
                         gamma=model_config.RL_GAMMA, verbose=0, device="cpu")
        logger.info("PPO 模型构建完成")
        return self.model

    def train(self, total_timesteps=None):
        if self.model is None:
            self.build_model()
        timesteps = total_timesteps or model_config.RL_TOTAL_TIMESTEPS
        logger.info(f"PPO 训练开始: {timesteps:,} timesteps")
        self.model.learn(total_timesteps=timesteps, progress_bar=True)
        self._is_trained = True
        logger.info("PPO 训练完成！")

    def predict(self, state, deterministic=True):
        if self.model is None:
            raise ValueError("模型未训练")
        return self.model.predict(state, deterministic=deterministic)

    def save(self, name="ppo_trader.zip"):
        if self.model is None:
            return
        self.model.save(str(MODELS_DIR / name))
        logger.info(f"PPO 已保存")

    def load(self, name="ppo_trader.zip"):
        from stable_baselines3 import PPO
        path = str(MODELS_DIR / name)
        if not __import__("os").path.exists(path):
            return False
        self.model = PPO.load(path, device="auto")
        self._is_trained = True
        return True

    def is_ready(self):
        return self._is_trained
