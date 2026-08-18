# services/model_train_service/trainers/__init__.py
"""Lazy trainer exports so importing GBDT does not require torch."""

from __future__ import annotations

from typing import Any

__all__ = [
    "TrainerBase",
    "GBDTTrainer",
    "TransformerTrainer",
    "TCNTrainer",
    "TFTTrainer",
    "RLTrainer",
]


def __getattr__(name: str) -> Any:
    if name == "TrainerBase":
        from services.model_train_service.trainers.trainer_base import TrainerBase

        return TrainerBase
    if name == "GBDTTrainer":
        from services.model_train_service.trainers.gbdt_trainer import GBDTTrainer

        return GBDTTrainer
    if name == "TransformerTrainer":
        from services.model_train_service.trainers.transformer_trainer import TransformerTrainer

        return TransformerTrainer
    if name == "TCNTrainer":
        from services.model_train_service.trainers.tcn_trainer import TCNTrainer

        return TCNTrainer
    if name == "TFTTrainer":
        from services.model_train_service.trainers.tft_trainer import TFTTrainer

        return TFTTrainer
    if name == "RLTrainer":
        from services.model_train_service.trainers.rl_trainer import RLTrainer

        return RLTrainer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
