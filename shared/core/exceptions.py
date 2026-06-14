"""shared/core/exceptions.py – Unified exception hierarchy for Quant AI Trader v2.

All custom exceptions inherit from QATException, enabling centralized
exception handling in FastAPI middleware.
"""

from __future__ import annotations


class QATException(Exception):
    """Base exception for all Quant AI Trader errors.

    Attributes:
        message: Human-readable error message.
        code: Machine-readable error code (e.g. 'DATA_FETCH_FAILED').
        status_code: HTTP status code for API responses.
        details: Optional dict with extra diagnostic data.
    """

    def __init__(
        self,
        message: str,
        code: str | None = None,
        status_code: int = 500,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or "INTERNAL_ERROR"
        self.status_code = status_code
        self.details = details or {}

    def to_dict(self) -> dict:
        """Serialize exception to a JSON-safe dictionary."""
        result: dict = {
            "error": True,
            "code": self.code,
            "message": self.message,
            "status_code": self.status_code,
        }
        if self.details:
            result["details"] = self.details
        return result


# ── Data Layer Exceptions ────────────────────────────────────
class DataError(QATException):
    """Errors related to data fetching, storage, or validation."""

    def __init__(
        self,
        message: str,
        code: str = "DATA_ERROR",
        status_code: int = 502,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, code=code, status_code=status_code, details=details)


class DataFetchError(DataError):
    """Failed to fetch data from an external source (Tiger, yfinance, etc.)."""

    def __init__(
        self,
        message: str,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, code="DATA_FETCH_FAILED", status_code=502, details=details)


class DataValidationError(DataError):
    """Data failed validation checks (missing fields, wrong types, etc.)."""

    def __init__(
        self,
        message: str,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, code="DATA_VALIDATION_ERROR", status_code=422, details=details)


class DataAvailabilityError(DataError):
    """Requested data is not available for the given period/symbol."""

    def __init__(
        self,
        message: str,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, code="DATA_NOT_AVAILABLE", status_code=404, details=details)


# ── Model Layer Exceptions ───────────────────────────────────
class ModelError(QATException):
    """Errors related to model training, inference, or versioning."""

    def __init__(
        self,
        message: str,
        code: str = "MODEL_ERROR",
        status_code: int = 500,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, code=code, status_code=status_code, details=details)


class ModelTrainError(ModelError):
    """Error during model training pipeline."""

    def __init__(
        self,
        message: str,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, code="MODEL_TRAIN_FAILED", status_code=500, details=details)


class ModelInferenceError(ModelError):
    """Error during model inference / prediction."""

    def __init__(
        self,
        message: str,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, code="MODEL_INFERENCE_FAILED", status_code=500, details=details)


class ModelNotFoundError(ModelError):
    """Requested model version or artifact not found."""

    def __init__(
        self,
        message: str,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, code="MODEL_NOT_FOUND", status_code=404, details=details)


class ModelRegistryError(ModelError):
    """Error interacting with MLflow model registry."""

    def __init__(
        self,
        message: str,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, code="MODEL_REGISTRY_ERROR", status_code=502, details=details)


# ── Factor Layer Exceptions ─────────────────────────────────
class FactorError(QATException):
    """Errors related to factor computation, validation, or evaluation."""

    def __init__(
        self,
        message: str,
        code: str = "FACTOR_ERROR",
        status_code: int = 500,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, code=code, status_code=status_code, details=details)


class FactorComputationError(FactorError):
    """Factor computation failed."""

    def __init__(
        self,
        message: str,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, code="FACTOR_COMPUTATION_FAILED", status_code=500, details=details)


class FactorNotFoundError(FactorError):
    """Factor not found in registry."""

    def __init__(
        self,
        message: str,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, code="FACTOR_NOT_FOUND", status_code=404, details=details)


# ── Risk Layer Exceptions ────────────────────────────────────
class RiskError(QATException):
    """Errors related to risk management and compliance checks."""

    def __init__(
        self,
        message: str,
        code: str = "RISK_ERROR",
        status_code: int = 403,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, code=code, status_code=status_code, details=details)


class RiskLimitBreachedError(RiskError):
    """A risk limit was breached; order rejected or position reduced."""

    def __init__(
        self,
        message: str,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, code="RISK_LIMIT_BREACHED", status_code=403, details=details)


class CircuitBreakerError(RiskError):
    """Circuit breaker tripped; trading halted."""

    def __init__(
        self,
        message: str,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, code="CIRCUIT_BREAKER_TRIPPED", status_code=503, details=details)


class MarginError(RiskError):
    """Margin call or insufficient margin for order."""

    def __init__(
        self,
        message: str,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, code="MARGIN_ERROR", status_code=403, details=details)


# ── Execution Layer Exceptions ───────────────────────────────
class ExecutionError(QATException):
    """Errors related to order execution and broker interaction."""

    def __init__(
        self,
        message: str,
        code: str = "EXECUTION_ERROR",
        status_code: int = 502,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, code=code, status_code=status_code, details=details)


class OrderRejectedError(ExecutionError):
    """Order was rejected by the broker/exchange."""

    def __init__(
        self,
        message: str,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, code="ORDER_REJECTED", status_code=422, details=details)


class OrderTimeoutError(ExecutionError):
    """Order did not fill within the allowed time window."""

    def __init__(
        self,
        message: str,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, code="ORDER_TIMEOUT", status_code=408, details=details)


class BrokerConnectionError(ExecutionError):
    """Lost connection to broker API."""

    def __init__(
        self,
        message: str,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, code="BROKER_CONNECTION_ERROR", status_code=502, details=details)


# ── Configuration & Validation ───────────────────────────────
class ConfigError(QATException):
    """Configuration-related errors (missing env vars, invalid configs)."""

    def __init__(
        self,
        message: str,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, code="CONFIG_ERROR", status_code=500, details=details)


class ValidationError(QATException):
    """General input validation error."""

    def __init__(
        self,
        message: str,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, code="VALIDATION_ERROR", status_code=422, details=details)
