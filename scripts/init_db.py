#!/usr/bin/env python3
"""scripts/init_db.py – Database initialization script for Quant AI Trader v2.

Operations:
1. Create all tables via SQLAlchemy metadata (or Alembic migrations)
2. Seed market_universe from configs/market_universe.py
3. Seed factor_registry from configs/factor_registry.py

Usage:
    python scripts/init_db.py              # Full init: create tables + seed
    python scripts/init_db.py --seed-only  # Only seed data
    python scripts/init_db.py --drop       # Drop all tables then recreate + seed
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date
from uuid import uuid4

from loguru import logger
from sqlalchemy import text

from configs.factor_registry import FACTOR_REGISTRY
from configs.market_universe import MARKET_UNIVERSE
from shared.core.logger import setup_logger
from shared.database.engine import close_engine, get_engine
from shared.database.session import async_session_factory
from shared.models.base import Base


async def create_tables(drop_first: bool = False) -> None:
    """Create all database tables from SQLAlchemy metadata.

    Args:
        drop_first: If True, drop all tables before creating.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        if drop_first:
            logger.warning("Dropping all tables...")
            await conn.run_sync(Base.metadata.drop_all)
            logger.info("All tables dropped")

        logger.info("Creating all tables...")
        await conn.run_sync(Base.metadata.create_all)
        logger.info("All tables created")


async def seed_market_universe() -> int:
    """Populate ticker_info table from MARKET_UNIVERSE config.

    Returns:
        Number of records inserted.
    """
    count = 0
    async with async_session_factory() as session:
        for market, stocks in MARKET_UNIVERSE.items():
            for stock in stocks:
                # Check if ticker already exists
                result = await session.execute(
                    text("SELECT 1 FROM ticker_info WHERE ticker = :ticker"),
                    {"ticker": stock["ticker"]},
                )
                if result.first():
                    continue

                await session.execute(
                    text(
                        """INSERT INTO ticker_info
                        (id, ticker, name, market, sector, currency, is_active, is_etf,
                         created_at, updated_at)
                        VALUES (:id, :ticker, :name, :market, :sector, :currency,
                                true, :is_etf, datetime('now'), datetime('now'))"""
                    ),
                    {
                        "id": uuid4().hex,
                        "ticker": stock["ticker"],
                        "name": stock["name"],
                        "market": stock["market"],
                        "sector": stock.get("sector", ""),
                        "currency": stock.get("currency", "USD"),
                        "is_etf": stock.get("sector") == "ETF",
                    },
                )
                count += 1

        await session.commit()
    logger.info(f"Seeded {count} ticker_info records")
    return count


async def seed_factor_registry() -> int:
    """Populate factor_definitions table from FACTOR_REGISTRY config.

    Returns:
        Number of records inserted.
    """
    count = 0
    async with async_session_factory() as session:
        for category, factors in FACTOR_REGISTRY.items():
            for factor in factors:
                # Check if already exists
                result = await session.execute(
                    text("SELECT 1 FROM factor_definitions WHERE factor_id = :fid"),
                    {"fid": factor["id"]},
                )
                if result.first():
                    continue

                await session.execute(
                    text(
                        """INSERT INTO factor_definitions
                        (id, factor_id, name, category, subcategory, description,
                         formula_ref, lookback_default, frequency, neutralizable,
                         direction, is_active, created_at, updated_at)
                        VALUES (:id, :factor_id, :name, :category, :subcategory,
                                :description, :formula_ref, :lookback_default, :frequency,
                                :neutralizable, :direction, true, datetime('now'), datetime('now'))"""
                    ),
                    {
                        "id": uuid4().hex,
                        "factor_id": factor["id"],
                        "name": factor["name"],
                        "category": factor["category"],
                        "subcategory": factor.get("subcategory", ""),
                        "description": factor.get("description", ""),
                        "formula_ref": factor.get("formula_ref", ""),
                        "lookback_default": factor.get("lookback_default", 21),
                        "frequency": factor.get("frequency", "daily"),
                        "neutralizable": factor.get("neutralizable", True),
                        "direction": factor.get("direction", 0),
                    },
                )
                count += 1

        await session.commit()
    logger.info(f"Seeded {count} factor_definitions records")
    return count


async def run_init(drop_first: bool = False, seed_only: bool = False) -> None:
    """Run the full database initialization.

    Args:
        drop_first: Drop all tables before creating.
        seed_only: Only seed data (skip table creation).
    """
    setup_logger()

    if not seed_only:
        logger.info("Step 1: Creating database tables...")
        await create_tables(drop_first=drop_first)
    else:
        logger.info("Skipping table creation (--seed-only)")

    logger.info("Step 2: Seeding market universe...")
    market_count = await seed_market_universe()

    logger.info("Step 3: Seeding factor registry...")
    factor_count = await seed_factor_registry()

    total_tickers = sum(len(stocks) for stocks in MARKET_UNIVERSE.values())
    total_factors = sum(len(factors) for factors in FACTOR_REGISTRY.values())

    logger.info(
        f"Database initialization complete: "
        f"{market_count}/{total_tickers} market records, "
        f"{factor_count}/{total_factors} factor records"
    )

    await close_engine()


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Initialize Quant AI Trader v2 database")
    parser.add_argument(
        "--drop",
        action="store_true",
        help="Drop all existing tables before recreating",
    )
    parser.add_argument(
        "--seed-only",
        action="store_true",
        help="Only seed data (skip table creation)",
    )
    args = parser.parse_args()

    asyncio.run(run_init(drop_first=args.drop, seed_only=args.seed_only))


if __name__ == "__main__":
    main()
