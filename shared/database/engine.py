"""shared/database/engine.py – SQLAlchemy async engine factory.

Creates and manages the async SQLAlchemy engine and session factory
based on settings from configs/settings.py.
"""

from __future__ import annotations

from typing import Optional

from loguru import logger
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from configs.settings import settings

# Global engine instance (lazy-initialized)
_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def get_engine() -> AsyncEngine:
    """Get or create the SQLAlchemy async engine singleton.

    Returns:
        The global AsyncEngine instance.

    Raises:
        RuntimeError: If engine creation fails.
    """
    global _engine
    if _engine is None:
        try:
            _engine = create_async_engine(
                settings.POSTGRES_URL,
                echo=settings.POSTGRES_ECHO_SQL,
                pool_size=settings.POSTGRES_POOL_SIZE,
                max_overflow=settings.POSTGRES_MAX_OVERFLOW,
                pool_timeout=settings.POSTGRES_POOL_TIMEOUT,
                pool_pre_ping=True,
                pool_recycle=3600,
            )
            logger.info(
                f"Created async engine: pool_size={settings.POSTGRES_POOL_SIZE}, "
                f"max_overflow={settings.POSTGRES_MAX_OVERFLOW}"
            )
        except Exception as e:
            logger.error(f"Failed to create async engine: {e}")
            raise RuntimeError(f"Database engine creation failed: {e}") from e
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get or create the async session factory singleton.

    Returns:
        The global async_sessionmaker instance.
    """
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
        logger.info("Created async session factory")
    return _session_factory


async def close_engine() -> None:
    """Gracefully close the async engine and dispose of the connection pool."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Async engine disposed")
