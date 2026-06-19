"""services/data_service/realtime/ws_consumer.py – WebSocket consumer for real-time data.

Connects to Tiger Broker's WebSocket for real-time quote streaming.
Reconnects automatically on disconnect with exponential backoff.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Optional

from loguru import logger

from services.data_service.config import data_config
from services.data_service.realtime.stream_writer import StreamWriter


class WebSocketConsumer:
    """Consumes real-time market data via WebSocket.

    Connects to Tiger Broker WebSocket API and forwards quotes
    to Redis Streams for downstream processing.

    Attributes:
        reconnect_delay: Base delay for reconnection attempts.
        max_reconnect_delay: Maximum reconnection delay.
        subscribed_tickers: Set of ticker symbols to subscribe to.
    """

    def __init__(
        self,
        stream_writer: StreamWriter | None = None,
        reconnect_delay: float | None = None,
    ) -> None:
        self.reconnect_delay = reconnect_delay or data_config.WS_RECONNECT_DELAY
        self.max_reconnect_delay = 300.0  # 5 minutes max
        self.subscribed_tickers: set[str] = set()
        self._writer = stream_writer or StreamWriter()
        self._running: bool = False
        self._connected: bool = False
        self._callbacks: list[Callable[[dict[str, Any]], None]] = []

    def on_quote(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Register a callback for incoming quotes.

        Args:
            callback: Function that receives a quote dict.
        """
        self._callbacks.append(callback)

    async def subscribe(self, tickers: list[str]) -> None:
        """Subscribe to real-time quotes for tickers.

        Args:
            tickers: List of ticker symbols to subscribe to.
        """
        self.subscribed_tickers.update(tickers)
        logger.info(f"Subscribed to {len(tickers)} tickers (total: {len(self.subscribed_tickers)})")

    async def unsubscribe(self, tickers: list[str]) -> None:
        """Unsubscribe from tickers.

        Args:
            tickers: Tickers to unsubscribe from.
        """
        self.subscribed_tickers.difference_update(tickers)

    async def start(self) -> None:
        """Start the WebSocket consumer (blocking)."""
        self._running = True
        logger.info("WebSocket consumer starting...")

        while self._running:
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"WebSocket error: {e}, reconnecting...")
                await asyncio.sleep(self.reconnect_delay)
                self.reconnect_delay = min(
                    self.reconnect_delay * 2, self.max_reconnect_delay
                )

        logger.info("WebSocket consumer stopped")

    async def stop(self) -> None:
        """Stop the WebSocket consumer gracefully."""
        self._running = False
        self._connected = False

    async def _connect_and_listen(self) -> None:
        """Connect to the WebSocket and process incoming messages.

        This is a framework implementation. Actual Tiger WebSocket
        connection requires tigeropen SDK which is initialized
        in the TigerClient.
        """
        self._connected = True
        logger.info("WebSocket connected (simulated — Tiger WS requires live session)")

        # In production, this would use tigeropen's WebSocket subscription:
        # ws_client = TigerWebSocketClient(config)
        # ws_client.subscribe_quote(self.subscribed_tickers)
        # ws_client.on_message = self._handle_message
        # ws_client.connect()

        # For now, keep the consumer alive and ready
        while self._running:
            await asyncio.sleep(1.0)

            # Periodically ping to check connection health
            if not self._running:
                break

    async def _handle_message(self, raw_message: str) -> None:
        """Process an incoming WebSocket message.

        Args:
            raw_message: JSON-encoded quote message.
        """
        try:
            data = json.loads(raw_message)
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON from WebSocket: {raw_message[:100]}")
            return

        # Extract quote data
        quote = self._parse_quote(data)

        if quote:
            # Write to Redis Stream for downstream consumers
            await self._writer.write_quote(quote["ticker"], quote)

            # Notify registered callbacks
            for cb in self._callbacks:
                try:
                    cb(quote)
                except Exception as e:
                    logger.error(f"Quote callback error: {e}")

    def _parse_quote(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """Parse raw WebSocket data into a standardized quote dict.

        Args:
            data: Raw message data.

        Returns:
            Standardized quote dict, or None if parsing fails.
        """
        try:
            return {
                "ticker": data.get("symbol", ""),
                "last": data.get("last", data.get("price")),
                "bid": data.get("bid"),
                "ask": data.get("ask"),
                "bid_size": data.get("bid_size"),
                "ask_size": data.get("ask_size"),
                "volume": data.get("volume"),
                "turnover": data.get("turnover"),
                "open": data.get("open"),
                "high": data.get("high"),
                "low": data.get("low"),
                "change_pct": data.get("change"),
                "timestamp": data.get("timestamp"),
            }
        except Exception:
            return None
