"""services/execution_service/api/schemas.py – Pydantic request/response models for execution API."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class OrderRequest(BaseModel):
    """Order placement request body."""

    ticker: str = Field(..., description="Ticker symbol")
    side: str = Field(..., description="Order side: BUY | SELL", pattern=r"^(BUY|SELL)$")
    quantity: int = Field(..., description="Order quantity (shares)", gt=0)
    order_type: str = Field(
        default="MKT",
        description="Order type: MKT | LMT",
        pattern=r"^(MKT|LMT)$",
    )
    limit_price: Optional[float] = Field(
        default=None, description="Limit price (required for LMT orders)", gt=0.0
    )
    algo: Optional[str] = Field(
        default=None, description="Execution algorithm: twap | vwap | pov | direct"
    )
    account: Optional[str] = Field(
        default=None, description="Trading account identifier"
    )


class OrderResult(BaseModel):
    """Order result response model."""

    order_id: str = Field(..., description="Unique order identifier (UUID)")
    ticker: str = Field(..., description="Ticker symbol")
    side: str = Field(..., description="Order side: BUY | SELL")
    quantity: int = Field(..., description="Order quantity (shares)")
    filled_price: Optional[float] = Field(
        default=None, description="Average filled price"
    )
    filled_qty: float = Field(default=0.0, description="Filled quantity so far")
    status: str = Field(
        ...,
        description="Order status: queued | submitted | partial_fill | filled | cancelled",
    )
    algo: Optional[str] = Field(default=None, description="Execution algorithm used")
    placed_at: float = Field(..., description="Order placement timestamp (Unix epoch)")
    updated_at: Optional[float] = Field(
        default=None, description="Last update timestamp (Unix epoch)"
    )
