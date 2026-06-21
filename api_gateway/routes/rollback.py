"""api_gateway/routes/rollback.py – One-click rollback endpoint.

POST /api/v2/execution/rollback
Resets the circuit breaker state and logs the rollback timestamp.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from loguru import logger

from services.execution_service.live.circuit_breaker import CircuitBreaker

router = APIRouter()

# Module-level circuit breaker instance (singleton per process)
_circuit_breaker: CircuitBreaker | None = None


def get_circuit_breaker() -> CircuitBreaker:
    """Get or create the singleton CircuitBreaker instance."""
    global _circuit_breaker
    if _circuit_breaker is None:
        _circuit_breaker = CircuitBreaker()
    return _circuit_breaker


@router.post("/execution/rollback")
async def rollback() -> dict:
    """Reset circuit breaker state and execute rollback.

    Returns:
        Success status with rollback timestamp.
    """
    cb = get_circuit_breaker()
    cb.reset()
    timestamp = datetime.now(timezone.utc).isoformat()
    logger.info(f"Rollback executed at {timestamp} — Circuit breaker reset")
    return {
        "success": True,
        "message": "Rollback executed — circuit breaker reset to stable state",
        "timestamp": timestamp,
    }
