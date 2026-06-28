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

    When Redis is unavailable, automatically degrades to in-memory cache
    (no TTL support, no persistence) without raising errors.

    Attributes:
        client: The underlying aioredis client.
        is_degraded: True when operating in memory-fallback mode.
        mode: Human-readable mode indicator.
    """

    def __init__(self) -> None:
        self._connected: bool = False
        self._degraded: bool = False
        # ── In-memory fallback cache ──────────────────────────
        self._memory_cache: dict[str, str] = {}

        # When REDIS_URL is empty, skip creating a real client entirely
        if not settings.REDIS_URL or not settings.REDIS_URL.strip():
            self._degraded = True
            self.client: Redis = None  # type: ignore[assignment]
            logger.debug("REDIS_URL is empty — operating in in-memory mode")
            return

        self.client: Redis = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
        )

    async def connect(self) -> None:
        """Establish connection to Redis. Idempotent.

        If Redis is unavailable, gracefully degrades to in-memory mode
        without raising an exception.
        """
        if self._connected or self._degraded:
            return
        try:
            await self.client.ping()
            self._connected = True
            logger.info("Redis client connected")
        except Exception as e:
            self._degraded = True
            logger.info(
                f"Redis unavailable ({e}), falling back to in-memory cache "
                f"(no persistence, no TTL)"
            )

    async def disconnect(self) -> None:
        """Gracefully close the Redis connection."""
        if self._connected:
            try:
                await self.client.aclose()  # type: ignore[attr-defined]
            except Exception:
                pass
            self._connected = False
            logger.info("Redis client disconnected")
        self._degraded = False

    @property
    def is_connected(self) -> bool:
        """Check if the Redis client is connected to the real Redis server."""
        return self._connected

    @property
    def is_degraded(self) -> bool:
        """Check if operating in memory-fallback (degraded) mode."""
        return self._degraded

    @property
    def mode(self) -> str:
        """Human-readable mode indicator."""
        if self._connected:
            return "healthy"
        if self._degraded:
            return "degraded (fallback to memory)"
        return "unknown"

    # ── Cache Operations ─────────────────────────────────────
    async def cache_get(self, key: str) -> Optional[str]:
        """Get a value from the cache.

        Args:
            key: Cache key.

        Returns:
            Cached value string, or None if not found.
        """
        if self._connected:
            return await self.client.get(key)
        if self._degraded:
            return self._memory_cache.get(key)
        return None

    async def cache_get_json(self, key: str) -> Optional[Any]:
        """Get and deserialize a JSON value from the cache.

        Args:
            key: Cache key.

        Returns:
            Deserialized Python object, or None.
        """
        if self._connected:
            raw = await self.client.get(key)
            if raw is None:
                return None
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                logger.warning(f"Failed to decode JSON from cache key: {key}")
                return None
        if self._degraded:
            raw = self._memory_cache.get(key)
            if raw is None:
                return None
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                logger.warning(f"Failed to decode JSON from cache key: {key}")
                return None
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
            ttl: Time-to-live in seconds (default 300s). Ignored in degraded mode.

        Returns:
            True if set successfully.
        """
        if isinstance(value, (dict, list)):
            value = json.dumps(value, default=str)
        if self._connected:
            return await self.client.setex(key, ttl, value)
        if self._degraded:
            self._memory_cache[key] = value
            return True
        return False

    async def cache_delete(self, key: str) -> int:
        """Delete a cache key.

        Args:
            key: Cache key to delete.

        Returns:
            Number of keys deleted.
        """
        if self._connected:
            return await self.client.delete(key)
        if self._degraded:
            if key in self._memory_cache:
                del self._memory_cache[key]
                return 1
            return 0
        return 0

    async def cache_exists(self, key: str) -> bool:
        """Check if a cache key exists.

        Args:
            key: Cache key.

        Returns:
            True if key exists.
        """
        if self._connected:
            return await self.client.exists(key) > 0
        if self._degraded:
            return key in self._memory_cache
        return False

    async def cache_ttl(self, key: str) -> int:
        """Get the remaining TTL of a cache key.

        Args:
            key: Cache key.

        Returns:
            Remaining TTL in seconds, -1 if no TTL, -2 if key doesn't exist.
        """
        if self._connected:
            return await self.client.ttl(key)
        if self._degraded:
            return -1 if key in self._memory_cache else -2
        return -2

    # ── Stream Operations ────────────────────────────────────
    async def stream_add(
        self,
        stream: str,
        data: dict[str, Any],
        max_len: int = 10000,
    ) -> str:
        """Add an entry to a Redis Stream.

        In degraded mode, silently returns a placeholder ID.

        Args:
            stream: Stream name.
            data: Dictionary of field-value pairs.
            max_len: Maximum stream length (older entries trimmed).

        Returns:
            The entry ID (or placeholder in degraded mode).
        """
        if self._degraded:
            logger.debug(f"Redis degraded — stream_add '{stream}' skipped")
            return "0-0"
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

        In degraded mode, returns an empty list.

        Args:
            stream: Stream name.
            count: Maximum number of entries to read.
            block: Blocking timeout in ms (0 = non-blocking).
            start_id: Start reading from this entry ID.

        Returns:
            List of deserialized stream entries.
        """
        if self._degraded:
            return []
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

        In degraded mode, returns an empty list.

        Args:
            stream: Stream name.
            start: Start entry ID (or "-" for beginning).
            end: End entry ID (or "+" for end).
            count: Maximum entries.

        Returns:
            List of entries.
        """
        if self._degraded:
            return []
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

        In degraded mode, silently returns 0.

        Args:
            channel: Channel name.
            message: Message to publish.

        Returns:
            Number of subscribers that received the message.
        """
        if self._degraded:
            logger.debug(f"Redis degraded — publish to '{channel}' skipped")
            return 0
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

        In degraded mode, returns False without error.

        Returns:
            True if Redis responds.
        """
        if self._degraded:
            return False
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
