"""
Tiger API 滑动窗口限流器
- 60秒窗口，最多10个API调用
- 令牌桶 + 优先级队列
- 线程安全的全局单例
"""
import time
import threading
from collections import deque
from typing import Callable, Optional
from loguru import logger


class TigerRateLimiter:
    """
    滑动窗口限流器

    设计:
    - 窗口: 60 秒
    - 限制: 10 calls (Tiger API 硬限制)
    - 策略: 令牌桶 + 优先级队列
    - 线程安全

    用法:
        limiter = TigerRateLimiter()
        if limiter.acquire(priority=1):  # 阻塞直到获得令牌
            result = api_call()
            limiter.release()
    """

    def __init__(self, max_calls: int = 10, window: float = 60.0):
        """
        Args:
            max_calls: 窗口内最大调用次数
            window: 滑动窗口时长（秒）
        """
        self.max_calls = max_calls
        self.window = window
        self._call_times: deque[float] = deque()
        self._lock = threading.Lock()
        self._wait_lock = threading.Condition(self._lock)

        logger.info(f"🚦 限流器初始化: {max_calls} calls / {window}s 窗口")

    def _clean_expired(self) -> int:
        """清理过期记录，返回可用配额"""
        now = time.time()
        while self._call_times and self._call_times[0] < now - self.window:
            self._call_times.popleft()
        return self.max_calls - len(self._call_times)

    @property
    def available(self) -> int:
        """当前可用配额"""
        with self._lock:
            return self._clean_expired()

    @property
    def used(self) -> int:
        """当前已用配额"""
        with self._lock:
            self._clean_expired()
            return len(self._call_times)

    def can_call(self) -> bool:
        """非阻塞检查是否可以发起调用"""
        with self._lock:
            return self._clean_expired() > 0

    def acquire(self, timeout: Optional[float] = None) -> bool:
        """
        获取调用令牌（阻塞等待）

        Args:
            timeout: 最大等待时间（秒），None 为无限等待

        Returns:
            True 如果获得令牌，False 如果超时
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
        """释放一个令牌（用于在 acquire 后决定不调用时）"""
        with self._lock:
            if self._call_times:
                self._call_times.pop()
                self._wait_lock.notify()

    def wait_and_call(self, func: Callable, *args, timeout: Optional[float] = None, **kwargs):
        """
        等待令牌后执行函数，异常安全

        Args:
            func: 要执行的函数
            *args, **kwargs: 传递给 func 的参数
            timeout: 等待令牌的超时时间

        Returns:
            func 的返回值，或 None (超时/异常)
        """
        if not self.acquire(timeout=timeout):
            logger.warning("⏰ 限流器超时，放弃调用")
            return None

        try:
            result = func(*args, **kwargs)
            return result
        except Exception as e:
            logger.error(f"❌ 限流调用异常: {e}")
            return None
        # 注意：不调用 release()，因为 API 调用已消耗配额

    def wait_for_token(self, timeout: Optional[float] = None) -> bool:
        """等待可用令牌（acquire 的别名，语义更清晰）"""
        return self.acquire(timeout=timeout)

    def get_stats(self) -> dict:
        """获取限流器统计信息"""
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


# 全局单例
rate_limiter = TigerRateLimiter(max_calls=10, window=60.0)
