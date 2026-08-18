"""services/model_train_service/hyperopt/optuna_runner.py – Optuna hyperparameter search.

Bayesian optimisation with ≥100 trials, parallel studies.
Supports GBDT, Transformer, TCN, TFT model types.
"""

from __future__ import annotations

from typing import Any, Optional

import optuna
from loguru import logger

from services.model_train_service.config import train_config
from services.model_train_service.data_loader import create_dataset, split_features_target
from services.model_train_service.trainers.gbdt_trainer import GBDTTrainer
from services.model_train_service.trainers.tcn_trainer import TCNTrainer
from services.model_train_service.trainers.transformer_trainer import TransformerTrainer


def run_hyperopt(
    model_type: str = "gbdt",
    tickers: list[str] | None = None,
    n_trials: int = 100,
    start_date: str = "2023-01-01",
    end_date: str = "2024-12-31",
    device: str | None = None,
) -> dict[str, Any]:
    """Run Optuna Bayesian hyperparameter search.

    Args:
        model_type: One of 'gbdt', 'transformer', 'tcn', 'tft'.
        tickers: Ticker symbols for training data.
        n_trials: Number of Optuna trials.
        start_date: Start date for training data.
        end_date: End date for training data.
        device: Optional compute device hint (cpu/cuda/mps).

    Returns:
        Dict with best_params and best_value.
    """
    tickers = tickers or ["AAPL"]
    if device:
        logger.info(f"Hyperopt device hint: {device}")
    df = create_dataset(tickers, start_date, end_date, include_factors=True)

    if df is None or len(df) < 200:
        raise ValueError(f"Insufficient data: {len(df) if df is not None else 0} rows")

    X, y = split_features_target(df)

    if model_type == "gbdt":
        objective_fn = _create_gbdt_objective(X, y)
    elif model_type == "transformer":
        objective_fn = _create_transformer_objective(X, y)
    elif model_type == "tcn":
        objective_fn = _create_tcn_objective(X, y)
    elif model_type == "tft":
        objective_fn = _create_tft_objective(X, y)
    else:
        raise ValueError(f"Unsupported model type for hyperopt: {model_type}")

    study = optuna.create_study(
        direction="minimize",
        study_name=f"hyperopt_{model_type}",
        storage=None,  # In-memory
        load_if_exists=False,
    )

    study.optimize(
        objective_fn,
        n_trials=n_trials,
        n_jobs=train_config.HYPEROPT_N_JOBS,
        show_progress_bar=True,
    )

    logger.info(f"Hyperopt {model_type} complete: best_value={study.best_value:.6f}")
    logger.info(f"Best params: {study.best_params}")

    return {
        "best_params": study.best_params,
        "best_value": study.best_value,
        "n_trials": n_trials,
        "study_name": study.study_name,
    }


def _create_gbdt_objective(
    X: "pd.DataFrame",
    y: "pd.Series",
) -> Any:
    """Create Optuna objective for GBDT."""
    import numpy as np
    from sklearn.model_selection import TimeSeriesSplit

    def objective(trial: optuna.Trial) -> float:
        params = {
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "num_leaves": trial.suggest_int("num_leaves", 8, 128, log=True),
            "feature_fraction": trial.suggest_float("feature_fraction", 0.5, 1.0),
            "bagging_fraction": trial.suggest_float("bagging_fraction", 0.5, 1.0),
            "bagging_freq": trial.suggest_int("bagging_freq", 1, 10),
            "n_estimators": trial.suggest_int("n_estimators", 100, 1000),
        }

        trainer = GBDTTrainer(
            gbdt_type=trial.suggest_categorical("gbdt_type", ["lightgbm", "xgboost"]),
            params=params,
        )

        tscv = TimeSeriesSplit(n_splits=3)
        losses = []

        for train_idx, val_idx in tscv.split(X):
            X_tr, X_vl = X.iloc[train_idx], X.iloc[val_idx]
            y_tr, y_vl = y.iloc[train_idx], y.iloc[val_idx]

            try:
                metrics = trainer.fit(X_tr, y_tr, X_vl, y_vl)
                losses.append(metrics.get("val_rmse", metrics.get("val_loss", 1.0)))
            except Exception:
                return 1.0

        return float(np.mean(losses))

    return objective


def _create_transformer_objective(
    X: "pd.DataFrame",
    y: "pd.Series",
) -> Any:
    """Create Optuna objective for Transformer."""
    import numpy as np
    from sklearn.model_selection import TimeSeriesSplit

    def objective(trial: optuna.Trial) -> float:
        d_model = trial.suggest_categorical("d_model", [64, 128, 256])
        n_heads = trial.suggest_categorical("n_heads", [4, 8])
        n_layers = trial.suggest_int("n_layers", 2, 6)
        dropout = trial.suggest_float("dropout", 0.05, 0.3)
        lr = trial.suggest_float("lr", 1e-5, 1e-2, log=True)
        batch_size = trial.suggest_categorical("batch_size", [64, 128, 256])

        trainer = TransformerTrainer(
            d_model=d_model, n_heads=n_heads, n_layers=n_layers,
            dropout=dropout, seq_len=64,
        )

        tscv = TimeSeriesSplit(n_splits=2)
        losses = []

        for train_idx, val_idx in tscv.split(X):
            X_tr, X_vl = X.iloc[train_idx], X.iloc[val_idx]
            y_tr, y_vl = y.iloc[train_idx], y.iloc[val_idx]

            try:
                metrics = trainer.fit(X_tr, y_tr, X_vl, y_vl,
                                       epochs=30, batch_size=batch_size, lr=lr)
                losses.append(metrics.get("val_loss", 1.0))
            except Exception:
                return 1.0

        return float(np.mean(losses))

    return objective


def _create_tcn_objective(
    X: "pd.DataFrame",
    y: "pd.Series",
) -> Any:
    """Create Optuna objective for TCN."""
    import numpy as np
    from sklearn.model_selection import TimeSeriesSplit

    def objective(trial: optuna.Trial) -> float:
        num_layers = trial.suggest_int("num_layers", 2, 6)
        channels = [trial.suggest_categorical(f"ch_{i}", [32, 64, 128]) for i in range(num_layers)]
        kernel_size = trial.suggest_int("kernel_size", 2, 7)
        dropout = trial.suggest_float("dropout", 0.05, 0.3)
        lr = trial.suggest_float("lr", 1e-5, 1e-2, log=True)

        trainer = TCNTrainer(
            num_channels=channels, kernel_size=kernel_size,
            dropout=dropout, seq_len=64,
        )

        tscv = TimeSeriesSplit(n_splits=2)
        losses = []

        for train_idx, val_idx in tscv.split(X):
            X_tr, X_vl = X.iloc[train_idx], X.iloc[val_idx]
            y_tr, y_vl = y.iloc[train_idx], y.iloc[val_idx]

            try:
                metrics = trainer.fit(X_tr, y_tr, X_vl, y_vl,
                                       epochs=30, batch_size=128, lr=lr)
                losses.append(metrics.get("val_loss", 1.0))
            except Exception:
                return 1.0

        return float(np.mean(losses))

    return objective


def _create_tft_objective(
    X: "pd.DataFrame",
    y: "pd.Series",
) -> Any:
    """Create Optuna objective for TFT."""
    import numpy as np
    from sklearn.model_selection import TimeSeriesSplit

    def objective(trial: optuna.Trial) -> float:
        hidden_dim = trial.suggest_categorical("hidden_dim", [32, 64, 128])
        n_heads = trial.suggest_categorical("n_heads", [2, 4])
        lstm_layers = trial.suggest_int("lstm_layers", 1, 2)
        dropout = trial.suggest_float("dropout", 0.05, 0.3)
        lr = trial.suggest_float("lr", 1e-5, 1e-2, log=True)

        from services.model_train_service.trainers.tft_trainer import TFTTrainer
        trainer = TFTTrainer(
            hidden_dim=hidden_dim, n_heads=n_heads,
            lstm_layers=lstm_layers, dropout=dropout, seq_len=64,
        )

        tscv = TimeSeriesSplit(n_splits=2)
        losses = []

        for train_idx, val_idx in tscv.split(X):
            X_tr, X_vl = X.iloc[train_idx], X.iloc[val_idx]
            y_tr, y_vl = y.iloc[train_idx], y.iloc[val_idx]

            try:
                metrics = trainer.fit(X_tr, y_tr, X_vl, y_vl,
                                       epochs=30, batch_size=128, lr=lr)
                losses.append(metrics.get("val_loss", 1.0))
            except Exception:
                return 1.0

        return float(np.mean(losses))

    return objective
