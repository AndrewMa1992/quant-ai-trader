"""shared/redis_client.py – Redis client wrapper for Quant AI Trader v2.

Supports three modes:
1. Stream mode: Redis Streams for event-driven data pipelines
2. Cache mode: Key-value caching with TTL support
3. PubSub mode: Publish/subscribe for real-time messaging
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Optional, Union

import redis.asyncio as aioredis
from loguru import logger
from redis.asyncio import Redis

from configs.settings import settings

# Global Redis client singleton
_redis_client: Optional["RedisClient"] = None


class RedisClient:
    """Async Redis client wrapper providing Stream, Cache, and PubSub operations.

    Attributes:
        client: The underlying aioredis client.
    """

    def __init__(self) -> None:
        self.client: Redis = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
        )
        self._connected: bool = False

    async def connect(self) -> None:
        """Establish connection to Redis. Idempotent."""
        if not self._connected:
            await self.client.ping()
            self._connected = True
            logger.info("Redis client connected")

    async def disconnect(self) -> None:
        """Gracefully close the Redis connection."""
        if self._connected:
            await self.client.aclose()  # type: ignore[attr-defined]
            self._connected = False
            logger.info("Redis client disconnected")

    @property
    def is_connected(self) -> bool:
        """Check if the Redis client is connected."""
        return self._connected

    # ── Cache Operations ─────────────────────────────────────
    async def cache_get(self, key: str) -> Optional[str]:
        """Get a value from the cache.

        Args:
            key: Cache key.

        Returns:
            Cached value string, or None if not found.
        """
        return await self.client.get(key)

    async def cache_get_json(self, key: str) -> Optional[Any]:
        """Get and deserialize a JSON value from the cache.

        Args:
            key: Cache key.

        Returns:
            Deserialized Python object, or None.
        """
        raw = await self.client.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"Failed to decode JSON from cache key: {key}")
            return None

    async def cache_set(
        self,
        key: str,
        value: Union[str, dict, list],
        ttl: int = 300,
    ) -> bool:
        """Set a cache value with TTL.

        Args:
            key: Cache key.
            value: Value to cache (str, dict, or list).
            ttl: Time-to-live in seconds (default 300s).

        Returns:
            True if set successfully.
        """
        if isinstance(value, (dict, list)):
            value = json.dumps(value, default=str)
        return await self.client.setex(key, ttl, value)

    async def cache_delete(self, key: str) -> int:
        """Delete a cache key.

        Args:
            key: Cache key to delete.

        Returns:
            Number of keys deleted.
        """
        return await self.client.delete(key)

    async def cache_exists(self, key: str) -> bool:
        """Check if a cache key exists.

        Args:
            key: Cache key.

        Returns:
            True if key exists.
        """
        return await self.client.exists(key) > 0

    async def cache_ttl(self, key: str) -> int:
        """Get the remaining TTL of a cache key.

        Args:
            key: Cache key.

        Returns:
            Remaining TTL in seconds, -1 if no TTL, -2 if key doesn't exist.
        """
        return await self.client.ttl(key)

    # ── Stream Operations ────────────────────────────────────
    async def stream_add(
        self,
        stream: str,
        data: dict[str, Any],
        max_len: int = 10000,
    ) -> str:
        """Add an entry to a Redis Stream.

        Args:
            stream: Stream name.
            data: Dictionary of field-value pairs.
            max_len: Maximum stream length (older entries trimmed).

        Returns:
            The entry ID.
        """
        serialized = {k: json.dumps(v, default=str) if not isinstance(v, str) else v for k, v in data.items()}
        return await self.client.xadd(stream, serialized, maxlen=max_len)

    async def stream_read(
        self,
        stream: str,
        count: int = 100,
        block: int = 0,
        start_id: str = "0-0",
    ) -> list[dict[str, Any]]:
        """Read entries from a Redis Stream.

        Args:
            stream: Stream name.
            count: Maximum number of entries to read.
            block: Blocking timeout in ms (0 = non-blocking).
            start_id: Start reading from this entry ID.

        Returns:
            List of deserialized stream entries.
        """
        if block > 0:
            result = await self.client.xread(
                {stream: start_id}, count=count, block=block
            )
        else:
            result = await self.client.xread({stream: start_id}, count=count)

        entries: list[dict[str, Any]] = []
        if result:
            for stream_name, messages in result:
                for msg_id, fields in messages:
                    entry: dict[str, Any] = {"id": msg_id}
                    for k, v in fields.items():
                        try:
                            entry[k] = json.loads(v)
                        except (json.JSONDecodeError, TypeError):
                            entry[k] = v
                    entries.append(entry)
        return entries

    async def stream_range(
        self,
        stream: str,
        start: str = "-",
        end: str = "+",
        count: int = 100,
    ) -> list[dict[str, Any]]:
        """Read a range of entries from a Stream.

        Args:
            stream: Stream name.
            start: Start entry ID (or "-" for beginning).
            end: End entry ID (or "+" for end).
            count: Maximum entries.

        Returns:
            List of entries.
        """
        result = await self.client.xrange(stream, min=start, max=end, count=count)
        entries: list[dict[str, Any]] = []
        for msg_id, fields in result:
            entry: dict[str, Any] = {"id": msg_id}
            for k, v in fields.items():
                try:
                    entry[k] = json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    entry[k] = v
            entries.append(entry)
        return entries

    # ── PubSub Operations ────────────────────────────────────
    async def publish(self, channel: str, message: Union[str, dict]) -> int:
        """Publish a message to a Redis channel.

        Args:
            channel: Channel name.
            message: Message to publish.

        Returns:
            Number of subscribers that received the message.
        """
        if isinstance(message, dict):
            message = json.dumps(message, default=str)
        return await self.client.publish(channel, message)

    async def subscribe(self, channel: str) -> aioredis.client.PubSub:
        """Subscribe to a Redis channel.

        Args:
            channel: Channel name.

        Returns:
            A PubSub object for async iteration.
        """
        pubsub = self.client.pubsub()
        await pubsub.subscribe(channel)
        return pubsub

    # ── General Operations ───────────────────────────────────
    async def ping(self) -> bool:
        """Ping Redis to check connectivity.

        Returns:
            True if Redis responds.
        """
        return await self.client.ping()


async def get_redis() -> RedisClient:
    """Get or create the global Redis client singleton.

    Returns:
        The RedisClient instance.
    """
    global _redis_client
    if _redis_client is None:
        _redis_client = RedisClient()
        await _redis_client.connect()
    return _redis_client


async def close_redis() -> None:
    """Gracefully disconnect the global Redis client."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.disconnect()
        _redis_client = None
        logger.info("Redis client closed")
