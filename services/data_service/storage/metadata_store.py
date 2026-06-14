"""services/data_service/storage/metadata_store.py – Database metadata operations.

CRUD for:
- ticker_info (symbols, sectors, market)
- data_quality_log (ingestion/cleaning audit trail)
- universe membership management
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

from loguru import logger
from sqlalchemy import text

from shared.database.session import async_session_factory


class MetadataStore:
    """PostgreSQL-based metadata store for ticker info and data quality logs."""

    # ── Ticker Info CRUD ─────────────────────────────────────
    async def upsert_ticker(self, ticker_data: dict[str, Any]) -> None:
        """Insert or update a ticker_info record.

        Args:
            ticker_data: Dictionary with ticker metadata fields.
        """
        async with async_session_factory() as session:
            await session.execute(
                text(
                    """INSERT INTO ticker_info
                    (id, ticker, name, market, sector, industry, currency, exchange,
                     is_active, is_etf, market_cap, shares_outstanding, created_at, updated_at)
                    VALUES (gen_random_uuid(), :ticker, :name, :market, :sector, :industry,
                            :currency, :exchange, true, :is_etf, :market_cap,
                            :shares_outstanding, now(), now())
                    ON CONFLICT (ticker) DO UPDATE SET
                        name = EXCLUDED.name,
                        sector = EXCLUDED.sector,
                        industry = EXCLUDED.industry,
                        market_cap = EXCLUDED.market_cap,
                        shares_outstanding = EXCLUDED.shares_outstanding,
                        is_active = EXCLUDED.is_active,
                        updated_at = now()"""
                ),
                {
                    "ticker": ticker_data.get("ticker", ""),
                    "name": ticker_data.get("name", ""),
                    "market": ticker_data.get("market", ""),
                    "sector": ticker_data.get("sector", ""),
                    "industry": ticker_data.get("industry", ""),
                    "currency": ticker_data.get("currency", "USD"),
                    "exchange": ticker_data.get("exchange", ""),
                    "is_etf": ticker_data.get("sector") == "ETF",
                    "market_cap": ticker_data.get("market_cap"),
                    "shares_outstanding": ticker_data.get("shares_outstanding"),
                },
            )
            await session.commit()

    async def get_ticker(self, ticker: str) -> Optional[dict[str, Any]]:
        """Get ticker info by symbol.

        Args:
            ticker: Stock ticker symbol.

        Returns:
            Ticker info dict or None.
        """
        async with async_session_factory() as session:
            result = await session.execute(
                text("SELECT * FROM ticker_info WHERE ticker = :ticker"),
                {"ticker": ticker},
            )
            row = result.fetchone()
            if row is None:
                return None
            return dict(row._mapping)

    async def list_tickers_by_market(self, market: str) -> list[dict[str, Any]]:
        """List all active tickers in a market.

        Args:
            market: Market code (US/HK/SG/AU/NZ).

        Returns:
            List of ticker info dicts.
        """
        async with async_session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT * FROM ticker_info WHERE market = :market AND is_active = true"
                ),
                {"market": market},
            )
            return [dict(row._mapping) for row in result.fetchall()]

    async def set_inactive(self, ticker: str) -> None:
        """Mark a ticker as inactive.

        Args:
            ticker: Stock ticker.
        """
        async with async_session_factory() as session:
            await session.execute(
                text(
                    "UPDATE ticker_info SET is_active = false, updated_at = now() "
                    "WHERE ticker = :ticker"
                ),
                {"ticker": ticker},
            )
            await session.commit()

    # ── Data Quality Log ─────────────────────────────────────
    async def log_quality_check(
        self,
        ticker: str,
        source: str,
        bar_count: int,
        quality_score: float,
        issues: list[str] | None = None,
    ) -> None:
        """Log a data quality check result.

        Uses raw SQL since data_quality_log may not have a dedicated ORM model yet.
        Args:
            ticker: Stock ticker.
            source: Data source (yfinance, tiger, eodhd).
            bar_count: Number of bars ingested.
            quality_score: Quality score 0.0-1.0.
            issues: List of quality issues found.
        """
        try:
            async with async_session_factory() as session:
                await session.execute(
                    text(
                        """INSERT INTO alerts
                        (id, alert_type, severity, title, message, source, ticker,
                         is_read, is_resolved, slack_sent, created_at, updated_at)
                        VALUES (gen_random_uuid(), 'DATA', :severity, :title, :message,
                                :source, :ticker, false, false, false, now(), now())"""
                    ),
                    {
                        "severity": "WARNING" if issues else "INFO",
                        "title": f"Data quality: {ticker} ({source})",
                        "message": (
                            f"Bars: {bar_count}, Score: {quality_score:.2f}"
                            + (f", Issues: {'; '.join(issues)}" if issues else "")
                        ),
                        "source": source,
                        "ticker": ticker,
                    },
                )
                await session.commit()
        except Exception as e:
            logger.warning(f"Failed to log quality check for {ticker}: {e}")

    # ── Universe Management ──────────────────────────────────
    async def get_universe_summary(self) -> dict[str, Any]:
        """Get universe summary statistics.

        Returns:
            Dict with counts per market and sector.
        """
        async with async_session_factory() as session:
            result = await session.execute(
                text(
                    """SELECT market, COUNT(*) as count
                    FROM ticker_info WHERE is_active = true
                    GROUP BY market ORDER BY market"""
                )
            )
            by_market = {row.market: row.count for row in result.fetchall()}

            result2 = await session.execute(
                text(
                    """SELECT market, sector, COUNT(*) as count
                    FROM ticker_info WHERE is_active = true AND sector IS NOT NULL
                    GROUP BY market, sector ORDER BY market, sector"""
                )
            )
            by_sector: dict[str, dict[str, int]] = {}
            for row in result2.fetchall():
                if row.market not in by_sector:
                    by_sector[row.market] = {}
                by_sector[row.market][row.sector] = row.count

            return {
                "total_active": sum(by_market.values()),
                "by_market": by_market,
                "by_sector": by_sector,
            }
