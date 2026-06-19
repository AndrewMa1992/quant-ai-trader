"""shared/core/helpers.py – Common utility functions and decorators.

Includes:
- retry decorator with exponential backoff
- timeit context manager for performance measurement
- chunked iterator for batching
- async versions of core utilities
"""

from __future__ import annotations

import asyncio
import functools
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any, ParamSpec, TypeVar

from loguru import logger

P = ParamSpec("P")
T = TypeVar("T")


# ── Retry Decorator ──────────────────────────────────────────
def retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    logger_name: str | None = None,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorator: retry a function with exponential backoff on failure.

    Args:
        max_attempts: Maximum number of attempts (including the first).
        delay: Initial delay between retries in seconds.
        backoff_factor: Multiplier for delay on each retry.
        exceptions: Tuple of exception types to catch.
        logger_name: Optional logger name for retry messages.

    Returns:
        Decorated function with retry logic.
    """
    log = logger.bind(name=logger_name or "retry")

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            last_exception: Exception | None = None
            current_delay = delay

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == max_attempts:
                        log.error(
                            f"{func.__name__} failed after {max_attempts} attempts: {e}"
                        )
                        raise
                    log.warning(
                        f"{func.__name__} attempt {attempt}/{max_attempts} failed: {e}. "
                        f"Retrying in {current_delay:.1f}s..."
                    )
                    time.sleep(current_delay)
                    current_delay *= backoff_factor

            # Should never reach here, but for type safety
            if last_exception:
                raise last_exception
            raise RuntimeError(f"{func.__name__}: unexpected retry failure")

        return wrapper

    return decorator


# ── Async Retry Decorator ────────────────────────────────────
def async_retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    logger_name: str | None = None,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorator: retry an async function with exponential backoff.

    Args:
        max_attempts: Maximum number of attempts.
        delay: Initial delay between retries in seconds.
        backoff_factor: Multiplier for delay on each retry.
        exceptions: Tuple of exception types to catch.
        logger_name: Optional logger name.

    Returns:
        Decorated async function with retry logic.
    """
    log = logger.bind(name=logger_name or "async_retry")

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            last_exception: Exception | None = None
            current_delay = delay

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)  # type: ignore[return-value]
                except exceptions as e:
                    last_exception = e
                    if attempt == max_attempts:
                        log.error(
                            f"{func.__name__} failed after {max_attempts} attempts: {e}"
                        )
                        raise
                    log.warning(
                        f"{func.__name__} attempt {attempt}/{max_attempts} failed: {e}. "
                        f"Retrying in {current_delay:.1f}s..."
                    )
                    await asyncio.sleep(current_delay)
                    current_delay *= backoff_factor

            if last_exception:
                raise last_exception
            raise RuntimeError(f"{func.__name__}: unexpected retry failure")

        return wrapper  # type: ignore[return-value]

    return decorator


# ── Timeit Context Manager ───────────────────────────────────
@contextmanager
def timeit(label: str = "operation", logger_name: str | None = None) -> Iterator[None]:
    """Context manager to measure and log execution time.

    Usage:
        with timeit("factor_calculation"):
            calculate_factors()

    Args:
        label: Description of the operation being timed.
        logger_name: Optional logger name.
    """
    log = logger.bind(name=logger_name or "timeit")
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        log.info(f"{label} completed in {elapsed:.4f}s")


# ── Async Timeit Context Manager ─────────────────────────────
@asynccontextmanager
async def async_timeit(
    label: str = "operation", logger_name: str | None = None
) -> AsyncIterator[None]:
    """Async context manager to measure and log execution time.

    Usage:
        async with async_timeit("predict"):
            predictions = await model.predict(data)

    Args:
        label: Description of the operation.
        logger_name: Optional logger name.
    """
    log = logger.bind(name=logger_name or "async_timeit")
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        log.info(f"{label} completed in {elapsed:.4f}s")


# ── Chunked Iterator ─────────────────────────────────────────
def chunked(
    iterable: list[T] | Iterator[T],
    chunk_size: int,
) -> Iterator[list[T]]:
    """Split an iterable into fixed-size chunks.

    Args:
        iterable: Input iterable or list.
        chunk_size: Number of items per chunk.

    Yields:
        Lists of items, each up to chunk_size in length.
    """
    if isinstance(iterable, list):
        for i in range(0, len(iterable), chunk_size):
            yield iterable[i : i + chunk_size]
    else:
        chunk: list[T] = []
        for item in iterable:
            chunk.append(item)
            if len(chunk) >= chunk_size:
                yield chunk
                chunk = []
        if chunk:
            yield chunk


# ── Async Chunked Iterator ───────────────────────────────────
async def async_chunked(
    aiterable: AsyncIterator[T],
    chunk_size: int,
) -> AsyncIterator[list[T]]:
    """Split an async iterable into fixed-size chunks.

    Args:
        aiterable: Async iterable.
        chunk_size: Number of items per chunk.

    Yields:
        Lists of items, each up to chunk_size.
    """
    chunk: list[T] = []
    async for item in aiterable:
        chunk.append(item)
        if len(chunk) >= chunk_size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


# ── Safe Division ────────────────────────────────────────────
def safe_divide(
    numerator: float,
    denominator: float,
    default: float = 0.0,
) -> float:
    """Divide two numbers safely, returning a default if denominator is zero.

    Args:
        numerator: The numerator.
        denominator: The denominator.
        default: Value to return if denominator is 0.

    Returns:
        numerator / denominator, or default.
    """
    if denominator == 0.0:
        return default
    return numerator / denominator
