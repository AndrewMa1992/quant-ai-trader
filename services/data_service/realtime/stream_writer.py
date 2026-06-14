"""services/data_service/realtime/stream_writer.py – Redis Stream writer.

Writes market data snapshots to Redis Streams for factor computation
triggering and real-time dashboards.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger

from services.data_service.config import data_config
from shared.redis_client import RedisClient, get_redis


class StreamWriter:
    """Writes real-time market data to Redis Streams.

    Stream pattern: qat:market:{ticker} → field-value pairs
    Triggers downstream factor computation via stream consumers.
    """

    STREAM_PREFIX: str = "qat:market:"

    def __init__(self, max_len: int | None = None) -> None:
        self._max_len = max_len or data_config.STREAM_MAX_LEN
        self._redis: Optional[RedisClient] = None

    async def _get_redis(self) -> RedisClient:
        """Lazy-init Redis client.

        Returns:
            RedisClient instance.
        """
        if self._redis is None:
            self._redis = await get_redis()
        return self._redis

    async def write_quote(self, ticker: str, quote: dict[str, Any]) -> None:
        """Write a quote snapshot to the ticker's Redis Stream.

        Args:
            ticker: Stock ticker symbol.
            quote: Quote data dict.
        """
        try:
            redis = await self._get_redis()
            stream_name = f"{self.STREAM_PREFIX}{ticker}"

            data = {
                "ticker": ticker,
                "price": str(quote.get("last", "")),
                "bid": str(quote.get("bid", "")),
                "ask": str(quote.get("ask", "")),
                "volume": str(quote.get("volume", "")),
                "change_pct": str(quote.get("change_pct", "")),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            await redis.stream_add(stream_name, data, max_len=self._max_len)
        except Exception as e:
            logger.error(f"Failed to write quote for {ticker} to stream: {e}")

    async def write_batch(
        self, quotes: list[dict[str, Any]]
    ) -> None:
        """Write multiple quotes to their respective streams.

        Args:
            quotes: List of quote dicts (must contain 'ticker' key).
        """
        for quote in quotes:
            ticker = quote.get("ticker", "")
            if ticker:
                await self.write_quote(ticker, quote)

    async def write_signal(self, channel: str, signal: dict[str, Any]) -> None:
        """Publish a trading signal to a Redis PubSub channel.

        Args:
            channel: PubSub channel name.
            signal: Signal data dict.
        """
        try:
            redis = await self._get_redis()
            await redis.publish(channel, signal)
            logger.debug(f"Published signal to channel {channel}")
        except Exception as e:
            logger.error(f"Failed to publish signal: {e}")

    async def write_alert(self, alert_type: str, message: str, severity: str = "INFO") -> None:
        """Publish an alert to the alerts channel.

        Args:
            alert_type: Alert category (RISK, DATA, SYSTEM, etc.).
            message: Alert message.
            severity: Alert severity.
        """
        await self.write_signal("qat:alerts", {
            "type": alert_type,
            "severity": severity,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    async def get_latest_quote(self, ticker: str) -> Optional[dict[str, Any]]:
        """Get the most recent quote for a ticker from the stream.

        Args:
            ticker: Stock ticker symbol.

        Returns:
            Latest quote dict or None.
        """
        try:
            redis = await self._get_redis()
            stream_name = f"{self.STREAM_PREFIX}{ticker}"
            entries = await redis.stream_range(stream_name, start="-", end="+", count=1)
            return entries[0] if entries else None
        except Exception as e:
            logger.error(f"Failed to read latest quote for {ticker}: {e}")
            return None
