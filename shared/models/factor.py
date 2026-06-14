"""shared/models/factor.py – Factor-related ORM models.

Tables:
- factor_definitions: Factor registry reference
- factor_values: Computed factor values (time-series)
- factor_ic: Information Coefficient tracking
- factor_correlation: Factor cross-correlation matrix entries
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from shared.models.base import Base, TimestampMixin


class FactorDefinition(Base, TimestampMixin):
    """Factor registry reference table."""

    __tablename__ = "factor_definitions"

    factor_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    subcategory: Mapped[str] = mapped_column(String(50), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    formula_ref: Mapped[str] = mapped_column(String(200), nullable=True)
    lookback_default: Mapped[int] = mapped_column(Integer, default=21)
    frequency: Mapped[str] = mapped_column(String(20), default="daily")
    neutralizable: Mapped[bool] = mapped_column(default=True)
    direction: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    def __repr__(self) -> str:
        return f"<FactorDefinition(id={self.factor_id}, name={self.name})>"


class FactorValue(Base, TimestampMixin):
    """Time-series of computed factor values per ticker."""

    __tablename__ = "factor_values"
    __table_args__ = (
        UniqueConstraint("factor_id", "ticker", "value_date", name="uq_factor_value_ticker_date"),
    )

    factor_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    value_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    raw_value: Mapped[float] = mapped_column(Float, nullable=False)
    zscore: Mapped[float | None] = mapped_column(Float, nullable=True)
    percentile: Mapped[float | None] = mapped_column(Float, nullable=True)
    neutralized_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    market: Mapped[str] = mapped_column(String(10), nullable=False)

    def __repr__(self) -> str:
        return f"<FactorValue(factor={self.factor_id}, ticker={self.ticker}, date={self.value_date})>"


class FactorIC(Base, TimestampMixin):
    """Information Coefficient tracking for factor evaluation."""

    __tablename__ = "factor_ic"
    __table_args__ = (
        UniqueConstraint("factor_id", "ic_date", "horizon", name="uq_factor_ic_date_horizon"),
    )

    factor_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    ic_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    horizon: Mapped[str] = mapped_column(String(10), nullable=False)  # 1d, 5d, 21d
    rank_ic: Mapped[float] = mapped_column(Float, nullable=False)
    pearson_ic: Mapped[float] = mapped_column(Float, nullable=True)
    ic_std: Mapped[float] = mapped_column(Float, nullable=True)
    ic_tstat: Mapped[float] = mapped_column(Float, nullable=True)
    long_short_spread: Mapped[float] = mapped_column(Float, nullable=True)
    num_stocks: Mapped[int] = mapped_column(Integer, nullable=False)

    def __repr__(self) -> str:
        return f"<FactorIC(factor={self.factor_id}, date={self.ic_date}, IC={self.rank_ic:.4f})>"


class FactorCorrelation(Base, TimestampMixin):
    """Pairwise factor correlation matrix entries."""

    __tablename__ = "factor_correlation"
    __table_args__ = (
        UniqueConstraint("factor_id_1", "factor_id_2", "corr_date", name="uq_factor_corr_pair_date"),
    )

    factor_id_1: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    factor_id_2: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    corr_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    correlation: Mapped[float] = mapped_column(Float, nullable=False)
    lookback_days: Mapped[int] = mapped_column(Integer, default=63, nullable=False)

    def __repr__(self) -> str:
        return (
            f"<FactorCorrelation(f1={self.factor_id_1}, f2={self.factor_id_2}, "
            f"corr={self.correlation:.4f})>"
        )
