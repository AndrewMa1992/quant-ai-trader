"""Background Tiger → SQLite → frontend WebSocket sync.

Runs inside the execution-service lifespan so account/positions/orders
stay fresh even when the trading pipeline is between cycles.
"""
from __future__ import annotations

import asyncio
import os
from typing import Optional

from loguru import logger

SYNC_INTERVAL_SEC = float(os.getenv("QAT_TIGER_SYNC_INTERVAL_SEC", "30"))


async def run_tiger_sync_forever(stop_event: Optional[asyncio.Event] = None) -> None:
    """Pull Tiger paper/live books, persist, and push a WS snapshot."""
    from shared.tiger_bridge import sync_all_to_db
    from shared.ws_pusher import WsPusher

    pusher = WsPusher()
    logger.info("Tiger sync loop started (interval=%.0fs)", SYNC_INTERVAL_SEC)
    try:
        while stop_event is None or not stop_event.is_set():
            try:
                snap = await asyncio.to_thread(sync_all_to_db)
                if snap and not snap.get("error"):
                    await pusher.push_tiger_snapshot(snap)
                    logger.info(
                        "Tiger sync loop: cash=%.2f nav=%.2f pos=%s orders=%s",
                        float(snap.get("cash") or 0),
                        float(snap.get("nav") or 0),
                        snap.get("positions_synced", 0),
                        snap.get("orders_synced", 0),
                    )
                elif snap:
                    logger.warning("Tiger sync loop: %s", snap.get("error"))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Tiger sync loop failed: %s", exc)

            if stop_event is None:
                await asyncio.sleep(SYNC_INTERVAL_SEC)
                continue
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=SYNC_INTERVAL_SEC)
                break
            except asyncio.TimeoutError:
                continue
    finally:
        await pusher.close()
        logger.info("Tiger sync loop stopped")
