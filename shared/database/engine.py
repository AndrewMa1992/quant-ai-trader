"""shared/database/engine.py – SQLAlchemy async engine factory.

SQLite (Lightsail default) gets WAL pragmas + NullPool.
Postgres gets sized connection pooling.
"""

from __future__ import annotations

from typing import Optional

from loguru import logger
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from configs.settings import settings

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def _is_sqlite(url: str) -> bool:
    return "sqlite" in (url or "").lower()


def _apply_sqlite_pragmas(dbapi_conn, _connection_record) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.execute("PRAGMA cache_size=-64000")  # ~64MB
    cursor.execute("PRAGMA mmap_size=268435456")  # 256MB
    cursor.close()


def get_engine() -> AsyncEngine:
    """Get or create the SQLAlchemy async engine singleton."""
    global _engine
    if _engine is None:
        url = settings.POSTGRES_URL
        try:
            if _is_sqlite(url):
                _engine = create_async_engine(
                    url,
                    echo=settings.POSTGRES_ECHO_SQL,
                    poolclass=NullPool,
                    connect_args={"check_same_thread": False},
                )

                @event.listens_for(_engine.sync_engine, "connect")
                def _on_connect(dbapi_conn, connection_record):  # noqa: ANN001
                    _apply_sqlite_pragmas(dbapi_conn, connection_record)

                logger.info("Created async SQLite engine (WAL, NullPool, 64MB cache)")
            else:
                _engine = create_async_engine(
                    url,
                    echo=settings.POSTGRES_ECHO_SQL,
                    pool_size=settings.POSTGRES_POOL_SIZE,
                    max_overflow=settings.POSTGRES_MAX_OVERFLOW,
                    pool_timeout=settings.POSTGRES_POOL_TIMEOUT,
                    pool_pre_ping=True,
                    pool_recycle=3600,
                )
                logger.info(
                    f"Created async Postgres engine: pool_size={settings.POSTGRES_POOL_SIZE}, "
                    f"max_overflow={settings.POSTGRES_MAX_OVERFLOW}"
                )
        except Exception as e:
            logger.error(f"Failed to create async engine: {e}")
            raise RuntimeError(f"Database engine creation failed: {e}") from e
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get or create the async session factory singleton."""
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


def optimize_sqlite_file(path: str = "data/quant_trader.db") -> None:
    """Apply WAL pragmas to the on-disk SQLite file used by sync code paths."""
    import sqlite3
    from pathlib import Path

    p = Path(path)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA cache_size=-64000")
        conn.execute("PRAGMA mmap_size=268435456")
        conn.commit()
        for sql in (
            "CREATE INDEX IF NOT EXISTS idx_orders_ticker_ts ON orders(ticker, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_fills_ticker_ts ON fills(ticker, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_positions_ticker ON positions(ticker)",
        ):
            try:
                conn.execute(sql)
                conn.commit()
            except Exception:
                pass
        logger.info(f"SQLite optimized: {p} (WAL)")
    except Exception as exc:
        # Tables may not exist yet — pragmas still applied
        logger.debug(f"SQLite optimize partial: {exc}")
        try:
            conn.commit()
        except Exception:
            pass
    finally:
        conn.close()
