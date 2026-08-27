"""
Tiger API sliding-window rate limiter.
- 60-second window, at most 10 API calls
- Token bucket + priority queue
- Thread-safe global singleton
"""
import time
import threading
from collections import deque
from typing import Callable, Optional
from loguru import logger


class TigerRateLimiter:
    """
    Sliding-window rate limiter.

    Design:
    - Window: 60 seconds
    - Limit: 10 calls (Tiger API hard limit)
    - Strategy: token bucket + priority queue
    - Thread-safe

    Usage:
        limiter = TigerRateLimiter()
        if limiter.acquire(priority=1):  # block until a token is obtained
            result = api_call()
            limiter.release()
    """

    def __init__(self, max_calls: int = 10, window: float = 60.0):
        """
        Args:
            max_calls: maximum calls allowed inside the window
            window: sliding-window length in seconds
        """
        self.max_calls = max_calls
        self.window = window
        self._call_times: deque[float] = deque()
        self._lock = threading.Lock()
        self._wait_lock = threading.Condition(self._lock)

        logger.info(f"🚦 Rate limiter initialized: {max_calls} calls / {window}s window")

    def _clean_expired(self) -> int:
        """Drop expired timestamps and return remaining quota."""
        now = time.time()
        while self._call_times and self._call_times[0] < now - self.window:
            self._call_times.popleft()
        return self.max_calls - len(self._call_times)

    @property
    def available(self) -> int:
        """Currently available quota."""
        with self._lock:
            return self._clean_expired()

    @property
    def used(self) -> int:
        """Currently consumed quota."""
        with self._lock:
            self._clean_expired()
            return len(self._call_times)

    def can_call(self) -> bool:
        """Non-blocking check of whether a call can be issued."""
        with self._lock:
            return self._clean_expired() > 0

    def acquire(self, timeout: Optional[float] = None) -> bool:
        """
        Acquire a call token (blocking).

        Args:
            timeout: maximum wait in seconds; None waits forever

        Returns:
            True if a token was obtained, False on timeout
        """
        deadline = time.time() + timeout if timeout is not None else float("inf")

        with self._lock:
            while True:
                available = self._clean_expired()
                if available > 0:
                    self._call_times.append(time.time())
                    return True

                if timeout is not None:
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        return False
                    self._wait_lock.wait(timeout=min(remaining, 1.0))
                else:
                    self._wait_lock.wait(1.0)

    def release(self):
        """Release a token (used when acquire succeeded but the call is skipped)."""
        with self._lock:
            if self._call_times:
                self._call_times.pop()
                self._wait_lock.notify()

    def wait_and_call(self, func: Callable, *args, timeout: Optional[float] = None, **kwargs):
        """
        Wait for a token, then invoke the function with exception safety.

        Args:
            func: function to execute
            *args, **kwargs: arguments forwarded to func
            timeout: token-wait timeout

        Returns:
            func return value, or None on timeout/exception
        """
        if not self.acquire(timeout=timeout):
            logger.warning("⏰ Rate limiter timed out; skipping call")
            return None

        try:
            result = func(*args, **kwargs)
            return result
        except Exception as e:
            logger.error(f"❌ Rate-limited call failed: {e}")
            return None
        # Note: do not call release(); the API call already consumed quota

    def wait_for_token(self, timeout: Optional[float] = None) -> bool:
        """Wait for an available token (alias of acquire with clearer semantics)."""
        return self.acquire(timeout=timeout)

    def get_stats(self) -> dict:
        """Return rate-limiter statistics."""
        with self._lock:
            available = self._clean_expired()
            return {
                "max_calls": self.max_calls,
                "window_seconds": self.window,
                "used": len(self._call_times),
                "available": available,
                "next_release_in": round(
                    self._call_times[0] + self.window - time.time(), 1
                ) if self._call_times and available == 0 else 0,
            }


# Global singleton
rate_limiter = TigerRateLimiter(max_calls=10, window=60.0)
