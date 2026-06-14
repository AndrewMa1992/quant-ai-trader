"""shared/schema.py – Pydantic unified response models for Quant AI Trader v2.

Provides standardized API response formats with generic typing support.
All API endpoints should return these wrapped response types.
"""

from __future__ import annotations

from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    """Standard API response wrapper.

    Usage:
        return APIResponse(data=my_data, message="Success")
    """

    success: bool = Field(default=True, description="Indicates if the request was successful")
    message: str = Field(default="OK", description="Human-readable response message")
    data: Optional[T] = Field(default=None, description="Response payload")
    code: str = Field(default="SUCCESS", description="Machine-readable response code")

    model_config = {"json_schema_extra": {
        "example": {
            "success": True,
            "message": "OK",
            "data": {"key": "value"},
            "code": "SUCCESS",
        }
    }}


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated response wrapper for list endpoints.

    Usage:
        return PaginatedResponse(items=results, total=100, page=1, page_size=20)
    """

    success: bool = Field(default=True)
    message: str = Field(default="OK")
    items: list[T] = Field(default_factory=list, description="List of items for current page")
    total: int = Field(default=0, description="Total number of items across all pages")
    page: int = Field(default=1, description="Current page number (1-indexed)")
    page_size: int = Field(default=20, description="Number of items per page")
    total_pages: int = Field(default=0, description="Total number of pages")

    model_config = {"json_schema_extra": {
        "example": {
            "success": True,
            "message": "OK",
            "items": [],
            "total": 100,
            "page": 1,
            "page_size": 20,
            "total_pages": 5,
        }
    }}


class ErrorResponse(BaseModel):
    """Standardized error response.

    Usage:
        raise HTTPException(status_code=404, detail=ErrorResponse(...).model_dump())
    """

    success: bool = Field(default=False)
    message: str = Field(..., description="Human-readable error message")
    code: str = Field(default="ERROR", description="Machine-readable error code")
    details: Optional[dict[str, Any]] = Field(
        default=None, description="Optional error details"
    )
    status_code: int = Field(default=500, description="HTTP status code")

    model_config = {"json_schema_extra": {
        "example": {
            "success": False,
            "message": "Resource not found",
            "code": "NOT_FOUND",
            "details": {"resource": "model", "id": "abc-123"},
            "status_code": 404,
        }
    }}


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(default="healthy", description="Service status")
    version: str = Field(..., description="API version")
    uptime_seconds: float = Field(default=0.0, description="Server uptime in seconds")
    database: str = Field(default="unknown", description="Database connection status")
    redis: str = Field(default="unknown", description="Redis connection status")


def success_response(data: Any = None, message: str = "OK") -> dict:
    """Convenience function for creating success response dicts.

    Args:
        data: The response payload.
        message: Human-readable message.

    Returns:
        A dictionary conforming to the API response format.
    """
    return {"success": True, "message": message, "data": data, "code": "SUCCESS"}


def error_response(
    message: str,
    code: str = "ERROR",
    status_code: int = 500,
    details: dict[str, Any] | None = None,
) -> dict:
    """Convenience function for creating error response dicts.

    Args:
        message: Error message.
        code: Machine-readable error code.
        status_code: HTTP status code.
        details: Optional error details.

    Returns:
        A dictionary conforming to the error response format.
    """
    return {
        "success": False,
        "message": message,
        "code": code,
        "details": details,
        "status_code": status_code,
    }


def paginated_response(
    items: list[Any],
    total: int,
    page: int,
    page_size: int,
) -> PaginatedResponse:
    """Create a paginated response.

    Args:
        items: List of items for the current page.
        total: Total number of items.
        page: Current page number.
        page_size: Items per page.

    Returns:
        A PaginatedResponse instance.
    """
    total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
