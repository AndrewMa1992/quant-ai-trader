"""shared/models/portfolio.py – Portfolio-related ORM models.

Tables:
- portfolios: Portfolio snapshots
- positions: Position holdings
- trades: Executed trade records
- cash_flows: Deposit/withdrawal history
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from shared.models.base import Base, TimestampMixin


class Portfolio(Base, TimestampMixin):
    """Portfolio snapshot (daily NAV, exposures, metrics)."""

    __tablename__ = "portfolios"

    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True, index=True)
    nav: Mapped[float] = mapped_column(Float, nullable=False)
    gross_exposure: Mapped[float] = mapped_column(Float, nullable=False)
    net_exposure: Mapped[float] = mapped_column(Float, nullable=False)
    long_exposure: Mapped[float] = mapped_column(Float, nullable=False)
    short_exposure: Mapped[float] = mapped_column(Float, nullable=False)
    cash: Mapped[float] = mapped_column(Float, nullable=False)
    daily_pnl: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    daily_return: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    cumulative_return: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    var_95: Mapped[float] = mapped_column(Float, nullable=True)
    cvar_95: Mapped[float] = mapped_column(Float, nullable=True)
    sharpe_ratio: Mapped[float] = mapped_column(Float, nullable=True)
    max_drawdown: Mapped[float] = mapped_column(Float, nullable=True)
    drawdown_from_peak: Mapped[float] = mapped_column(Float, nullable=True)
    num_positions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    leverage: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    def __repr__(self) -> str:
        return f"<Portfolio(date={self.snapshot_date}, NAV={self.nav:,.0f})>"


class Position(Base, TimestampMixin):
    """Current or historical position holding."""

    __tablename__ = "positions"

    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    position_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    market: Mapped[str] = mapped_column(String(10), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_cost: Mapped[float] = mapped_column(Float, nullable=False)
    market_price: Mapped[float] = mapped_column(Float, nullable=False)
    market_value: Mapped[float] = mapped_column(Float, nullable=False)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    sector: Mapped[str] = mapped_column(String(100), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="USD")
    fx_rate: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    def __repr__(self) -> str:
        return (
            f"<Position(ticker={self.ticker}, qty={self.quantity}, "
            f"mv={self.market_value:,.0f}, pnl={self.unrealized_pnl:,.0f})>"
        )


class Trade(Base, TimestampMixin):
    """Record of executed trades."""

    __tablename__ = "trades"

    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    trade_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)  # BUY, SELL, SELL_SHORT, COVER
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    commission: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    slippage_bps: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    notional: Mapped[float] = mapped_column(Float, nullable=False)
    order_id: Mapped[str] = mapped_column(String(64), nullable=True, index=True)
    execution_id: Mapped[str] = mapped_column(String(64), nullable=True)
    signal_id: Mapped[str] = mapped_column(String(64), nullable=True)
    market: Mapped[str] = mapped_column(String(10), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="USD")
    strategy: Mapped[str] = mapped_column(String(50), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<Trade(ticker={self.ticker}, {self.side} {self.quantity}@{self.price}, "
            f"date={self.trade_date})>"
        )


class CashFlow(Base, TimestampMixin):
    """Cash flow records: deposits, withdrawals, dividends, interest."""

    __tablename__ = "cash_flows"

    flow_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    flow_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # DEPOSIT, WITHDRAWAL, DIVIDEND, INTEREST, COMMISSION, TAX, OTHER
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="USD")
    description: Mapped[str] = mapped_column(Text, nullable=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=True)  # For dividends
    trade_id: Mapped[str] = mapped_column(String(64), nullable=True)  # For commissions

    def __repr__(self) -> str:
        return f"<CashFlow(date={self.flow_date}, type={self.flow_type}, amount={self.amount:,.2f})>"
