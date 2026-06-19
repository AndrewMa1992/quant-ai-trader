"""shared/core/logger.py – Structured logging via Loguru for Quant AI Trader v2.

Features:
- JSON-structured format for production, colored for development
- Automatic rotation (10 MB or 7 days)
- Per-module loggers with appropriate levels
- Request ID injection for traceability
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from loguru import logger

from configs.settings import settings

# Track whether the logger has been configured globally
_logger_configured: bool = False


def setup_logger(
    log_level: str | None = None,
    log_dir: str | None = None,
    structured: bool | None = None,
) -> None:
    """Configure the Loguru root logger with rotation and formatting.

    Should be called once at application startup. Idempotent – subsequent
    calls are no-ops.

    Args:
        log_level: Override the default log level from settings.
        log_dir: Override the log directory from settings.
        structured: If True, use JSON format. Defaults to True in production.
    """
    global _logger_configured
    if _logger_configured:
        return

    level = log_level or settings.LOG_LEVEL
    directory = Path(log_dir or settings.LOG_DIR)
    directory.mkdir(parents=True, exist_ok=True)

    is_structured = structured if structured is not None else settings.is_production

    # Remove default handler
    logger.remove()

    if is_structured:
        # JSON-structured format for production / log aggregation
        logger.add(
            directory / "qat_{time:YYYY-MM-DD}.jsonl",
            level=level,
            rotation="10 MB",
            retention="7 days",
            compression="gz",
            serialize=True,
            format="{time} {level} {name}:{function}:{line} {message} {extra}",
            enqueue=True,
            backtrace=True,
            diagnose=settings.DEBUG,
        )
    else:
        # Colored format for development
        logger.add(
            directory / "qat_{time:YYYY-MM-DD}.log",
            level=level,
            rotation="10 MB",
            retention="7 days",
            compression="gz",
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
            enqueue=True,
            backtrace=True,
            diagnose=settings.DEBUG,
        )

    # Always add stderr for development visibility
    logger.add(
        sys.stderr,
        level=level,
        colorize=True,
        format=(
            "<green>{time:HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        backtrace=True,
        diagnose=settings.DEBUG,
    )

    _logger_configured = True
    logger.info(f"Logger initialized (level={level}, structured={is_structured})")


def get_logger(name: str | None = None) -> "logger":
    """Return a Loguru logger instance for the given module name.

    Ensures the logger is configured before returning.

    Args:
        name: Module name for context (e.g. '__name__').

    Returns:
        A Loguru logger instance.
    """
    if not _logger_configured:
        setup_logger()
    if name:
        return logger.bind(name=name)
    return logger


# Auto-configure on import (dev-friendly; production calls setup_logger explicitly)
if not _logger_configured:
    setup_logger()
