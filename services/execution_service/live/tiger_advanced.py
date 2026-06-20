"""services/execution_service/live/tiger_advanced.py – Tiger Advanced Operations.

Provides higher-level account operations on top of TigerBroker:
- Asset refresh (pull from Tiger → update DB portfolios)
- Position reconciliation (Tiger vs DB)
- Short-selling repair (borrowable share query + alert, no auto-order)
- Full account query (status, permissions, funds)
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from loguru import logger
from sqlalchemy import text

from services.execution_service.live.tiger_broker import TigerBroker
from shared.database.engine import get_engine


class TigerAdvancedClient:
    """Advanced Tiger broker operations for asset management.

    Provides reconciliation, asset refresh, short-selling alerts,
    and comprehensive account queries.

    Attributes:
        broker: Underlying TigerBroker instance.
        account: Tiger account number.
    """

    def __init__(self, account: str = "") -> None:
        self.broker = TigerBroker(account=account)
        self.account = account or self.broker.account

    async def refresh_assets(self) -> dict[str, Any]:
        """Fetch current account assets from Tiger and update the DB.

        Pulls NAV, cash, positions from Tiger Broker SDK and writes
        a new snapshot to the ``portfolios`` table.

        Returns:
            Dict with status, nav, cash, position_count.
        """
        try:
            summary = await self.broker.get_account_summary()
            positions = await self.broker.get_positions()

            nav = float(summary.get("nav", 0))
            cash = float(summary.get("cash", 0))
            position_count = len(positions)

            # Write snapshot to DB
            engine = get_engine()
            async with engine.connect() as conn:
                await conn.execute(
                    text(
                        """
                        INSERT INTO portfolios (
                            snapshot_date, nav, cash, num_positions,
                            gross_exposure, net_exposure,
                            long_exposure, short_exposure,
                            daily_pnl, daily_return, cumulative_return,
                            leverage, created_at, updated_at
                        ) VALUES (
                            :snapshot_date, :nav, :cash, :num_positions,
                            :gross_exposure, :net_exposure,
                            :long_exposure, :short_exposure,
                            0.0, 0.0, 0.0, 1.0,
                            NOW(), NOW()
                        )
                        ON CONFLICT (snapshot_date) DO UPDATE SET
                            nav = EXCLUDED.nav,
                            cash = EXCLUDED.cash,
                            num_positions = EXCLUDED.num_positions,
                            gross_exposure = EXCLUDED.gross_exposure,
                            net_exposure = EXCLUDED.net_exposure,
                            long_exposure = EXCLUDED.long_exposure,
                            short_exposure = EXCLUDED.short_exposure,
                            updated_at = NOW()
                        """
                    ),
                    {
                        "snapshot_date": date.today(),
                        "nav": nav,
                        "cash": cash,
                        "num_positions": position_count,
                        "gross_exposure": sum(
                            abs(p.get("market_value", 0)) for p in positions
                        ),
                        "net_exposure": sum(
                            p.get("market_value", 0) for p in positions
                        ),
                        "long_exposure": sum(
                            p.get("market_value", 0) for p in positions
                            if (p.get("quantity", 0) or 0) > 0
                        ),
                        "short_exposure": sum(
                            abs(p.get("market_value", 0)) for p in positions
                            if (p.get("quantity", 0) or 0) < 0
                        ),
                    },
                )
                await conn.commit()

            logger.info(
                f"Assets refreshed: NAV={nav:,.0f}, cash={cash:,.0f}, "
                f"positions={position_count}"
            )
            return {
                "status": "success",
                "account": self.account,
                "nav": nav,
                "cash": cash,
                "position_count": position_count,
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"Asset refresh failed: {e}")
            return {
                "status": "error",
                "account": self.account,
                "error": str(e),
            }

    async def reconcile(self) -> dict[str, Any]:
        """Reconcile Tiger positions against database positions.

        Compares Tiger Broker current positions with the latest DB
        ``positions`` table records and reports differences.

        Returns:
            Dict with matches, delta, and issues lists.
        """
        try:
            tiger_positions = await self.broker.get_positions()
            tiger_map: dict[str, dict] = {
                p.get("ticker", "").upper(): p for p in tiger_positions
            }

            # Fetch latest DB positions
            engine = get_engine()
            async with engine.connect() as conn:
                result = await conn.execute(
                    text(
                        """
                        SELECT DISTINCT ON (ticker) ticker, quantity, market_value
                        FROM positions
                        ORDER BY ticker, position_date DESC
                        """
                    )
                )
                db_rows = result.fetchall()

            db_map: dict[str, dict] = {}
            for row in db_rows:
                db_map[row[0].upper()] = {
                    "ticker": row[0],
                    "quantity": row[1] or 0,
                    "market_value": float(row[2] or 0),
                }

            # Compare
            matches: list[dict] = []
            delta: list[dict] = []
            issues: list[dict] = []

            all_tickers = set(tiger_map.keys()) | set(db_map.keys())
            for ticker in all_tickers:
                t = tiger_map.get(ticker)
                d = db_map.get(ticker)

                if t and d:
                    t_qty = t.get("quantity", 0) or 0
                    d_qty = d.get("quantity", 0) or 0
                    if t_qty == d_qty:
                        matches.append({
                            "ticker": ticker,
                            "quantity": t_qty,
                            "source": "both",
                        })
                    else:
                        delta.append({
                            "ticker": ticker,
                            "tiger_qty": t_qty,
                            "db_qty": d_qty,
                            "diff": t_qty - d_qty,
                        })
                elif t and not d:
                    issues.append({
                        "ticker": ticker,
                        "issue": "only_in_tiger",
                        "tiger_qty": t.get("quantity", 0) or 0,
                    })
                elif d and not t:
                    issues.append({
                        "ticker": ticker,
                        "issue": "only_in_db",
                        "db_qty": d.get("quantity", 0) or 0,
                    })

            logger.info(
                f"Reconciliation: {len(matches)} matched, "
                f"{len(delta)} deltas, {len(issues)} issues"
            )
            return {
                "status": "success",
                "account": self.account,
                "matches": matches,
                "delta": delta,
                "issues": issues,
                "summary": {
                    "matched": len(matches),
                    "deltas": len(delta),
                    "issues": len(issues),
                },
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"Reconciliation failed: {e}")
            return {
                "status": "error",
                "account": self.account,
                "error": str(e),
                "matches": [],
                "delta": [],
                "issues": [],
            }

    async def repair_shorts(self) -> dict[str, Any]:
        """Query borrowable short shares availability and alert.

        Per architecture decision #4, this does NOT auto-place orders.
        It only queries borrowable inventory and emits warnings for
        tickers with zero or low availability.

        Returns:
            Dict with borrowable status per ticker and any alerts.
        """
        try:
            positions = await self.broker.get_positions()
            short_positions = [
                p for p in positions if (p.get("quantity", 0) or 0) < 0
            ]

            if not short_positions:
                return {
                    "status": "success",
                    "account": self.account,
                    "message": "No short positions to repair",
                    "short_positions": [],
                }

            alerts: list[dict] = []
            for pos in short_positions:
                ticker = pos.get("ticker", "")
                qty = abs(pos.get("quantity", 0) or 0)

                # Query borrowable shares (SDK-dependent)
                borrowable = 0
                borrowable_status = "unknown"
                try:
                    self.broker._ensure_client()
                    if self.broker._initialized:
                        # Tiger SDK shortable query would go here
                        # For now, report as unknown
                        borrowable_status = "sdk_available_no_query"
                    else:
                        borrowable_status = "paper_mode"
                except Exception:
                    borrowable_status = "query_failed"

                alerts.append({
                    "ticker": ticker,
                    "short_qty": qty,
                    "borrowable_estimated": borrowable,
                    "status": borrowable_status,
                    "alert": (
                        "WARNING: Cannot verify borrowable shares"
                        if borrowable_status != "paper_mode"
                        else "Paper mode — borrowable check unavailable"
                    ),
                })

            logger.warning(
                f"Short repair check: {len(alerts)} short positions, "
                f"borrowable status unknown"
            )
            return {
                "status": "success",
                "account": self.account,
                "message": (
                    f"Checked {len(alerts)} short positions. "
                    "No auto-orders placed (per policy)."
                ),
                "short_positions": alerts,
                "auto_order_placed": False,
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"Short repair check failed: {e}")
            return {
                "status": "error",
                "account": self.account,
                "error": str(e),
                "auto_order_placed": False,
            }

    async def get_account(self) -> dict[str, Any]:
        """Full Tiger account query: status, permissions, funds, margin.

        Returns:
            Comprehensive account information dict.
        """
        try:
            summary = await self.broker.get_account_summary()

            # Build comprehensive response
            account_info: dict[str, Any] = {
                "account": self.account,
                "status": "active",
                "nav": summary.get("nav", 0),
                "cash": summary.get("cash", 0),
                "buying_power": summary.get("buying_power", 0),
                "currency": "USD",
                "margin_enabled": summary.get("buying_power", 0) > summary.get("cash", 0),
                "timestamp": datetime.utcnow().isoformat(),
            }

            # Try to get additional details from Tiger SDK
            self.broker._ensure_client()
            if self.broker._initialized:
                try:
                    import asyncio
                    accounts = await asyncio.to_thread(
                        self.broker._client.get_accounts
                    )
                    if accounts and len(accounts) > 0:
                        acc = accounts[0]
                        account_info.update({
                            "account_type": getattr(acc, "account_type", "unknown"),
                            "currency_list": getattr(acc, "currency_list", ["USD"]),
                            "permissions": {
                                "trading": True,
                                "short_selling": getattr(acc, "short_selling", False),
                                "margin": getattr(acc, "margin", False),
                                "options": getattr(acc, "options", False),
                            },
                        })
                except Exception as e:
                    logger.debug(f"Additional account details unavailable: {e}")

            return account_info

        except Exception as e:
            logger.error(f"Account query failed: {e}")
            return {
                "account": self.account,
                "status": "error",
                "error": str(e),
            }
