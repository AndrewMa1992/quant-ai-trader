"""shared/database/session.py – Async database session management.

Provides a FastAPI-compatible dependency for async database sessions,
as well as a standalone context manager for non-FastAPI usage.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.engine import get_session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an async database session.

    The session is automatically closed when the request completes.
    Rolls back on exception.

    Usage:
        @app.get("/data")
        async def get_data(session: AsyncSession = Depends(get_session)):
            ...

    Yields:
        An AsyncSession instance.
    """
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("Database session rolled back due to error")
        raise
    finally:
        await session.close()


@asynccontextmanager
async def async_session_factory() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for standalone async database sessions.

    Usage:
        async with async_session_factory() as session:
            result = await session.execute(...)

    Yields:
        An AsyncSession instance.
    """
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("Database session rolled back")
        raise
    finally:
        await session.close()
