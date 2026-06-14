"""shared/models/market_data.py – Market data ORM models.

Tables:
- daily_bars: End-of-day OHLCV bars
- minute_bars: Intraday OHLCV bars (1-minute resolution)
- corporate_actions: Splits, dividends, mergers
- ticker_info: Reference table for symbols
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.models.base import Base, TimestampMixin


class TickerInfo(Base, TimestampMixin):
    """Reference table for tradeable instruments."""

    __tablename__ = "ticker_info"

    ticker: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    market: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    sector: Mapped[str] = mapped_column(String(100), nullable=True)
    industry: Mapped[str] = mapped_column(String(200), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="USD")
    exchange: Mapped[str] = mapped_column(String(20), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    is_etf: Mapped[bool] = mapped_column(default=False, nullable=False)
    market_cap: Mapped[float] = mapped_column(Float, nullable=True)
    shares_outstanding: Mapped[float] = mapped_column(Float, nullable=True)

    # Relationships
    daily_bars: Mapped[list["DailyBar"]] = relationship(back_populates="ticker_info", lazy="selectin")
    minute_bars: Mapped[list["MinuteBar"]] = relationship(back_populates="ticker_info", lazy="selectin")

    def __repr__(self) -> str:
        return f"<TickerInfo(ticker={self.ticker}, market={self.market})>"


class DailyBar(Base, TimestampMixin):
    """End-of-day OHLCV bar data."""

    __tablename__ = "daily_bars"
    __table_args__ = (
        UniqueConstraint("ticker", "trade_date", name="uq_daily_bar_ticker_date"),
    )

    ticker: Mapped[str] = mapped_column(String(20), ForeignKey("ticker_info.ticker"), nullable=False, index=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    adj_close: Mapped[float] = mapped_column(Float, nullable=True)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    turnover: Mapped[float] = mapped_column(Float, nullable=True)
    vwap: Mapped[float] = mapped_column(Float, nullable=True)
    splits_factor: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    dividends_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Relationship
    ticker_info: Mapped["TickerInfo"] = relationship(back_populates="daily_bars")

    def __repr__(self) -> str:
        return f"<DailyBar(ticker={self.ticker}, date={self.trade_date}, close={self.close})>"


class MinuteBar(Base, TimestampMixin):
    """Intraday 1-minute OHLCV bar data."""

    __tablename__ = "minute_bars"
    __table_args__ = (
        UniqueConstraint("ticker", "bar_time", name="uq_minute_bar_ticker_time"),
    )

    ticker: Mapped[str] = mapped_column(String(20), ForeignKey("ticker_info.ticker"), nullable=False, index=True)
    bar_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    vwap: Mapped[float] = mapped_column(Float, nullable=True)
    trade_count: Mapped[int] = mapped_column(Integer, nullable=True)

    # Relationship
    ticker_info: Mapped["TickerInfo"] = relationship(back_populates="minute_bars")

    def __repr__(self) -> str:
        return f"<MinuteBar(ticker={self.ticker}, time={self.bar_time})>"


class CorporateAction(Base, TimestampMixin):
    """Corporate actions: splits, dividends, mergers, etc."""

    __tablename__ = "corporate_actions"

    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    action_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(20), nullable=False)  # SPLIT, DIVIDEND, MERGER, SPINOFF
    description: Mapped[str] = mapped_column(Text, nullable=True)
    ratio: Mapped[float] = mapped_column(Float, nullable=True)  # For splits (e.g. 2.0 = 2:1)
    amount: Mapped[float] = mapped_column(Float, nullable=True)  # For dividends
    currency: Mapped[str] = mapped_column(String(10), nullable=True)
    ex_date: Mapped[date] = mapped_column(Date, nullable=True)
    record_date: Mapped[date] = mapped_column(Date, nullable=True)
    pay_date: Mapped[date] = mapped_column(Date, nullable=True)

    def __repr__(self) -> str:
        return f"<CorporateAction(ticker={self.ticker}, type={self.action_type}, date={self.action_date})>"
