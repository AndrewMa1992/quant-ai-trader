"""shared/models/model.py – Model-related ORM models.

Tables:
- model_versions: ML model registry (versioned, linked to MLflow)
- model_metrics: Per-model evaluation metrics
- predictions: Model predictions (time-series)
- signals: Trading signals derived from predictions
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from shared.models.base import Base, TimestampMixin


class ModelVersion(Base, TimestampMixin):
    """ML model version registry — linked to MLflow run."""

    __tablename__ = "model_versions"

    model_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(30), nullable=False)
    model_type: Mapped[str] = mapped_column(String(30), nullable=False)  # xgboost, lightgbm, catboost, ensemble
    mlflow_run_id: Mapped[str] = mapped_column(String(100), nullable=True)
    mlflow_model_uri: Mapped[str] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="development", nullable=False)
    # development, staging, production, archived
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    training_start_date: Mapped[date] = mapped_column(Date, nullable=True)
    training_end_date: Mapped[date] = mapped_column(Date, nullable=True)
    target_horizon: Mapped[str] = mapped_column(String(10), nullable=False)  # 1d, 5d, 21d
    features_hash: Mapped[str] = mapped_column(String(64), nullable=True)
    parameters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    factor_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_production: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        UniqueConstraint("model_name", "version", name="uq_model_name_version"),
    )

    def __repr__(self) -> str:
        return f"<ModelVersion(name={self.model_name}, v={self.version}, type={self.model_type})>"


class ModelMetric(Base, TimestampMixin):
    """Model evaluation metrics per version."""

    __tablename__ = "model_metrics"
    __table_args__ = (
        UniqueConstraint("model_version_id", "metric_name", "eval_date", name="uq_model_metric"),
    )

    model_version_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    metric_name: Mapped[str] = mapped_column(String(50), nullable=False)
    metric_value: Mapped[float] = mapped_column(Float, nullable=False)
    eval_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    eval_set: Mapped[str] = mapped_column(String(20), nullable=False)  # train, val, test, oos
    horizon: Mapped[str] = mapped_column(String(10), nullable=True)
    market: Mapped[str] = mapped_column(String(10), nullable=True)

    def __repr__(self) -> str:
        return f"<ModelMetric(model={self.model_version_id}, {self.metric_name}={self.metric_value})>"


class Prediction(Base, TimestampMixin):
    """Model prediction output per ticker per date."""

    __tablename__ = "predictions"
    __table_args__ = (
        UniqueConstraint("model_version_id", "ticker", "prediction_date", name="uq_prediction"),
    )

    model_version_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    prediction_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    horizon: Mapped[str] = mapped_column(String(10), nullable=False)  # 1d, 5d, 21d
    predicted_return: Mapped[float] = mapped_column(Float, nullable=False)
    predicted_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_interval_lower: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_interval_upper: Mapped[float | None] = mapped_column(Float, nullable=True)
    feature_importance: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ensemble_weight: Mapped[float | None] = mapped_column(Float, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<Prediction(model={self.model_version_id}, ticker={self.ticker}, "
            f"ret={self.predicted_return:.4f})>"
        )


class Signal(Base, TimestampMixin):
    """Trading signals derived from model predictions, post risk-filter."""

    __tablename__ = "signals"
    __table_args__ = (
        UniqueConstraint("ticker", "signal_date", "horizon", name="uq_signal_ticker_date"),
    )

    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    signal_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    horizon: Mapped[str] = mapped_column(String(10), nullable=False)
    direction: Mapped[int] = mapped_column(Integer, nullable=False)  # 1=LONG, -1=SHORT, 0=FLAT
    strength: Mapped[float] = mapped_column(Float, nullable=False)  # 0.0 to 1.0
    target_weight: Mapped[float] = mapped_column(Float, nullable=False)
    predicted_return: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, nullable=True)
    is_executed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def __repr__(self) -> str:
        dir_str = "LONG" if self.direction > 0 else "SHORT" if self.direction < 0 else "FLAT"
        return f"<Signal(ticker={self.ticker}, dir={dir_str}, strength={self.strength:.2f})>"
