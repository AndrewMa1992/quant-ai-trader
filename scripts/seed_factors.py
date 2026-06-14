#!/usr/bin/env python3
"""scripts/seed_factors.py – Seed all 100+ factors from factor_registry into DB.

Usage:
    python scripts/seed_factors.py
    python scripts/seed_factors.py --clear   # Delete existing first
"""

from __future__ import annotations

import argparse
import asyncio

from loguru import logger

from configs.factor_registry import FACTOR_REGISTRY
from shared.core.logger import setup_logger
from shared.database.engine import close_engine
from shared.database.session import async_session_factory


async def seed_factors(clear: bool = False) -> dict[str, int]:
    """Insert factor definitions into the factor_definitions table.

    Args:
        clear: If True, delete all existing factor definitions first.

    Returns:
        Dict with counts per category.
    """
    async with async_session_factory() as session:
        from sqlalchemy import text

        if clear:
            logger.warning("Clearing all existing factor definitions...")
            await session.execute(text("DELETE FROM factor_definitions"))
            await session.commit()

        counts: dict[str, int] = {}
        total = 0

        for category, factors in FACTOR_REGISTRY.items():
            cat_count = 0
            for factor in factors:
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
                        VALUES (gen_random_uuid(), :factor_id, :name, :category,
                                :subcategory, :description, :formula_ref,
                                :lookback_default, :frequency, :neutralizable,
                                :direction, true, now(), now())"""
                    ),
                    {
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
                cat_count += 1
                total += 1

            counts[category] = cat_count

        await session.commit()
        logger.info(f"Seeded {total} factor definitions across {len(counts)} categories")
        return counts


async def main(clear: bool = False) -> None:
    setup_logger()
    counts = await seed_factors(clear=clear)
    for cat, n in counts.items():
        logger.info(f"  {cat}: {n} factors")
    logger.info(f"  Total: {sum(counts.values())} factors")
    await close_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--clear", action="store_true", help="Delete existing factors first")
    args = parser.parse_args()
    asyncio.run(main(clear=args.clear))
