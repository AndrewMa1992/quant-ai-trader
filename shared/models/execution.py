"""shared/models/execution.py – Execution-related ORM models.

Tables:
- orders: Order management records
- executions: Fill/execution records
- alerts: System alert messages
- circuit_breakers: Circuit breaker event log
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from shared.models.base import Base, TimestampMixin


class Order(Base, TimestampMixin):
    """Order management record — tracks order lifecycle."""

    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)  # BUY, SELL, SELL_SHORT, COVER
    order_type: Mapped[str] = mapped_column(String(20), nullable=False)  # MARKET, LIMIT, STOP, STOP_LIMIT
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    filled_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    # PENDING, SUBMITTED, PARTIAL_FILL, FILLED, CANCELLED, REJECTED, EXPIRED
    time_in_force: Mapped[str] = mapped_column(String(10), default="DAY", nullable=False)
    # DAY, GTC, IOC, FOK
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    market: Mapped[str] = mapped_column(String(10), nullable=False)
    strategy: Mapped[str | None] = mapped_column(String(50), nullable=True)
    signal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_paper: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<Order(id={self.order_id}, {self.side} {self.ticker} "
            f"qty={self.quantity}, status={self.status})>"
        )


class Execution(Base, TimestampMixin):
    """Trade execution / fill record."""

    __tablename__ = "executions"

    execution_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    notional: Mapped[float] = mapped_column(Float, nullable=False)
    commission: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    market: Mapped[str] = mapped_column(String(10), nullable=False)
    exchange: Mapped[str] = mapped_column(String(20), nullable=True)
    venue: Mapped[str] = mapped_column(String(20), nullable=True)
    is_paper: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    def __repr__(self) -> str:
        return (
            f"<Execution(id={self.execution_id}, {self.ticker} "
            f"{self.quantity}@{self.price}, notional={self.notional:,.0f})>"
        )


class Alert(Base, TimestampMixin):
    """System alert messages — risk, execution, data pipeline."""

    __tablename__ = "alerts"

    alert_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    # RISK, EXECUTION, DATA, MODEL, SYSTEM
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    # INFO, WARNING, ERROR, CRITICAL
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    slack_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    def __repr__(self) -> str:
        return f"<Alert(type={self.alert_type}, severity={self.severity}, title={self.title})>"


class CircuitBreaker(Base, TimestampMixin):
    """Circuit breaker event log — tracks trading halts."""

    __tablename__ = "circuit_breakers"

    trigger_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # DAILY_LOSS, DRAWDOWN, VOLATILITY, CORRELATION, MANUAL
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    threshold_value: Mapped[float] = mapped_column(Float, nullable=False)
    actual_value: Mapped[float] = mapped_column(Float, nullable=False)
    affected_markets: Mapped[str] = mapped_column(String(100), nullable=True)
    cooling_off_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<CircuitBreaker(type={self.trigger_type}, active={self.is_active}, "
            f"triggered={self.triggered_at})>"
        )
