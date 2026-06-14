"""services/model_infer_service/ensemble/market_state.py – Market state detection.

Uses HMM hidden states and GARCH volatility for regime classification.
Outputs market regime to inform model subset selection.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from loguru import logger


class MarketStateDetector:
    """Detects market regime for adaptive model selection.

    Regimes:
    - 0: Bull (low vol, positive trend)
    - 1: Bear (high vol, negative trend)
    - 2: Sideways/Crisis (extreme vol)
    """

    N_REGIMES: int = 3

    def __init__(self, n_regimes: int = 3) -> None:
        self.n_regimes = n_regimes
        self._hmm_model: Any = None
        self._fitted: bool = False
        self._current_state: int = 0
        self._state_probabilities: np.ndarray | None = None

    def fit(self, returns: np.ndarray, volatilities: np.ndarray | None = None) -> int:
        """Fit HMM to detect market states.

        Args:
            returns: Array of daily returns.
            volatilities: Optional GARCH/EWMA volatility estimates.

        Returns:
            Current detected regime.
        """
        try:
            from hmmlearn import hmm

            # Build feature matrix
            features: list[np.ndarray] = [returns.reshape(-1, 1)]

            if volatilities is not None:
                features.append(volatilities.reshape(-1, 1))
            else:
                # Compute rolling volatility
                vol = pd.Series(returns).rolling(21).std().fillna(0).values
                features.append(vol.reshape(-1, 1))

            # Add rolling metrics
            ret_5d = pd.Series(returns).rolling(5).mean().fillna(0).values
            features.append(ret_5d.reshape(-1, 1))

            X = np.hstack(features)
            X = np.where(np.isfinite(X), X, 0.0)

            self._hmm_model = hmm.GaussianHMM(
                n_components=self.n_regimes,
                covariance_type="full",
                n_iter=100,
                random_state=42,
            )
            self._hmm_model.fit(X)

            # Predict current state
            states = self._hmm_model.predict(X)
            self._current_state = int(states[-1])
            self._state_probabilities = self._hmm_model.predict_proba(X)[-1]
            self._fitted = True

            logger.info(f"Market state fitted: current regime={self._current_state}")
            return self._current_state

        except ImportError:
            logger.warning("hmmlearn not installed — using simple heuristic")
            return self._heuristic_detect(returns)
        except Exception as e:
            logger.error(f"HMM fitting failed: {e}")
            return self._heuristic_detect(returns)

    def _heuristic_detect(self, returns: np.ndarray) -> int:
        """Simple heuristic based on return and volatility thresholds.

        Args:
            returns: Daily returns.

        Returns:
            Estimated regime.
        """
        recent = returns[-63:]  # ~3 months
        if len(recent) < 20:
            return 0

        mean_ret = float(np.mean(recent))
        vol = float(np.std(recent))

        if vol > 0.03:
            self._current_state = 2  # Crisis
        elif mean_ret < -0.0005:
            self._current_state = 1  # Bear
        else:
            self._current_state = 0  # Bull

        self._state_probabilities = np.zeros(self.n_regimes)
        self._state_probabilities[self._current_state] = 1.0

        return self._current_state

    def predict(self, features: np.ndarray) -> int:
        """Predict current market state from features.

        Args:
            features: Feature array.

        Returns:
            Regime ID.
        """
        if self._fitted and self._hmm_model is not None:
            try:
                state = int(self._hmm_model.predict(features.reshape(1, -1))[0])
                self._current_state = state
                return state
            except Exception:
                pass

        return self._current_state

    @property
    def current_state(self) -> int:
        return self._current_state

    @property
    def state_name(self) -> str:
        names = {0: "bull", 1: "bear", 2: "crisis"}
        return names.get(self._current_state, "unknown")

    @property
    def state_probabilities(self) -> dict[int, float]:
        if self._state_probabilities is None:
            return {0: 1.0, 1: 0.0, 2: 0.0}
        return {i: float(p) for i, p in enumerate(self._state_probabilities)}

    def get_model_subset(self, available_models: list[str]) -> list[str]:
        """Select model subset based on market regime.

        Bull: All models weighted toward momentum
        Bear: Defensive models (GBDT, TFT)
        Crisis: Conservative models (GBDT only)

        Args:
            available_models: List of available model names.

        Returns:
            Recommended model subset.
        """
        if self._current_state == 0:  # Bull
            return available_models
        elif self._current_state == 1:  # Bear
            return [m for m in available_models if m in ("gbdt", "tft", "transformer")]
        else:  # Crisis
            return [m for m in available_models if m in ("gbdt", "tft")]

    def compute_garch_volatility(self, returns: np.ndarray) -> np.ndarray:
        """Compute GARCH(1,1) volatility estimate.

        Args:
            returns: Daily returns array.

        Returns:
            Conditional volatility estimates.
        """
        try:
            from arch import arch_model

            model = arch_model(returns, vol="Garch", p=1, q=1)
            result = model.fit(disp="off")
            return result.conditional_volatility.values

        except ImportError:
            logger.debug("arch package not installed — using EWMA")
            return self._ewma_volatility(returns)
        except Exception as e:
            logger.debug(f"GARCH failed: {e} — using EWMA")
            return self._ewma_volatility(returns)

    @staticmethod
    def _ewma_volatility(returns: np.ndarray, span: int = 21) -> np.ndarray:
        """EWMA volatility estimate.

        Args:
            returns: Daily returns.
            span: EWMA span.

        Returns:
            Volatility array.
        """
        return pd.Series(returns).ewm(span=span).std().fillna(0).values
