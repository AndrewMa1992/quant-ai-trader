"""services/risk_service/api/schemas.py – Pydantic request/response models for risk API."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class RiskCheckRequest(BaseModel):
    """Order-level risk check request body."""

    ticker: str = Field(..., description="Ticker symbol to check")
    quantity: int = Field(..., description="Order quantity (shares)", gt=0)
    price: float = Field(..., description="Order price per share", gt=0.0)
    portfolio_state: Optional[dict] = Field(
        default=None,
        description="Current portfolio state dict with positions, nav, etc.",
    )
    signal_strength: Optional[float] = Field(
        default=None,
        description="Model signal strength [-1, 1]",
        ge=-1.0,
        le=1.0,
    )


class RiskCheckResult(BaseModel):
    """Risk check result response model."""

    passed: bool = Field(..., description="Whether the order passes risk checks")
    reason: str = Field(..., description="Human-readable reason for the result")
    warnings: list[str] = Field(
        default_factory=list, description="Advisory warnings (non-blocking)"
    )
    sanitized_weights: Optional[dict[str, float]] = Field(
        default=None, description="Risk-adjusted portfolio weights if modified"
    )
