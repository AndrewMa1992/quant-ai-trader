"""services/model_train_service/framework/early_stopping.py – Early stopping.

Monitors validation loss and stops training when no improvement
for `patience` consecutive rounds. Restores best weights.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

import numpy as np
from loguru import logger


class EarlyStopping:
    """Early stopping monitor for iterative training.

    Attributes:
        patience: Number of rounds with no improvement before stopping.
        min_delta: Minimum change to qualify as improvement.
        mode: 'min' (lower is better) or 'max' (higher is better).
        restore_best: Whether to restore the best model state on stop.
    """

    def __init__(
        self,
        patience: int = 10,
        min_delta: float = 1e-6,
        mode: str = "min",
        restore_best: bool = True,
    ) -> None:
        self.patience = patience
        self.min_delta = min_delta
        self.mode = mode
        self.restore_best = restore_best

        self._best_score: float | None = None
        self._best_epoch: int = 0
        self._counter: int = 0
        self._should_stop: bool = False
        self._best_state: Any = None
        self._get_state_fn: Callable[[], Any] | None = None
        self._restore_fn: Callable[[Any], None] | None = None

    def reset(self) -> None:
        """Reset the early stopper state."""
        self._best_score = None
        self._best_epoch = 0
        self._counter = 0
        self._should_stop = False
        self._best_state = None

    def register_callbacks(
        self,
        get_state_fn: Callable[[], Any] | None = None,
        restore_fn: Callable[[Any], None] | None = None,
    ) -> None:
        """Register functions to save and restore model state.

        Args:
            get_state_fn: Returns current model state (e.g., deepcopy of state_dict).
            restore_fn: Restores model state from saved state.
        """
        self._get_state_fn = get_state_fn
        self._restore_fn = restore_fn

    def update(self, score: float, epoch: int) -> bool:
        """Update the monitor with the latest validation score.

        Args:
            score: Current validation metric.
            epoch: Current epoch number.

        Returns:
            True if training should stop.
        """
        if self._best_score is None:
            self._best_score = score
            self._best_epoch = epoch
            self._counter = 0
            self._capture_best_state()
            return False

        improved = (
            (score < self._best_score - self.min_delta)
            if self.mode == "min"
            else (score > self._best_score + self.min_delta)
        )

        if improved:
            self._best_score = score
            self._best_epoch = epoch
            self._counter = 0
            self._capture_best_state()
        else:
            self._counter += 1
            if self._counter > self.patience:
                self._should_stop = True
                logger.info(
                    f"Early stopping at epoch {epoch}: best={self._best_score:.6f} "
                    f"at epoch {self._best_epoch}"
                )
                if self.restore_best and self._best_state is not None and self._restore_fn:
                    self._restore_fn(self._best_state)
                    logger.info("Restored best model state")
                return True

        return False

    def _capture_best_state(self) -> None:
        """Capture the best model state for restoration."""
        if self._get_state_fn and self.restore_best:
            try:
                self._best_state = self._get_state_fn()
            except Exception as e:
                logger.warning(f"Failed to capture best state: {e}")
                self._best_state = None

    @property
    def should_stop(self) -> bool:
        return self._should_stop

    @property
    def best_score(self) -> float:
        return self._best_score if self._best_score is not None else float("inf")

    @property
    def best_epoch(self) -> int:
        return self._best_epoch


class EarlyStoppingWrapper:
    """Convenience wrapper that combines EarlyStopping with PyTorch training loops."""

    def __init__(
        self,
        patience: int = 10,
        min_delta: float = 1e-6,
        mode: str = "min",
        verbose: bool = True,
    ) -> None:
        self.stopper = EarlyStopping(
            patience=patience, min_delta=min_delta, mode=mode, restore_best=True,
        )
        self.verbose = verbose
        self.best_epoch = 0
        self.best_score: float | None = None

    def __call__(self, score: float, epoch: int, model: Any = None) -> bool:
        """Check if training should stop.

        Args:
            score: Validation metric.
            epoch: Current epoch.
            model: Optional model to save/restore state.

        Returns:
            True to stop training.
        """
        if model is not None:
            import copy
            self.stopper.register_callbacks(
                get_state_fn=lambda m=model: copy.deepcopy(
                    getattr(m, "state_dict", lambda: {})()
                ),
                restore_fn=lambda state, m=model: getattr(m, "load_state_dict", lambda _: None)(state),
            )

        should_stop = self.stopper.update(score, epoch)
        self.best_epoch = self.stopper.best_epoch
        self.best_score = self.stopper.best_score

        if should_stop and self.verbose:
            logger.info(f"EarlyStopping triggered: best={self.best_score:.6f} at epoch {self.best_epoch}")

        return should_stop
