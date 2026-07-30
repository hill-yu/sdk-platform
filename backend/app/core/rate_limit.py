"""内存 IP 速率限制（不依赖 Redis）"""
import time
from collections import defaultdict
from collections.abc import Callable

from fastapi import Request, HTTPException


class SimpleRateLimiter:
    def __init__(
        self,
        max_requests: int = 10,
        window_seconds: int = 1,
        max_keys: int = 10000,
        clock: Callable[[], float] | None = None,
    ):
        self.max = max_requests
        self.window = window_seconds
        self.max_keys = max_keys
        self.clock = clock or time.time
        self._store: dict[str, list[float]] = defaultdict(list)
        self._cleanup_counter = 0

    async def __call__(self, request: Request):
        ip = request.client.host if request.client else "unknown"
        now = self.clock()
        self._store[ip] = [t for t in self._store[ip] if now - t < self.window]
        if len(self._store[ip]) >= self.max:
            raise HTTPException(status_code=429, detail="Too many requests")
        self._store[ip].append(now)

        # 每 1000 次请求清理一次全部过期 IP
        self._cleanup_counter += 1
        if self._cleanup_counter >= 1000:
            self._cleanup_counter = 0
            self.cleanup(now)

    def cleanup(self, now: float | None = None) -> None:
        """清理所有 IP 的过期时间戳，并把字典容量限制在 max_keys 内。"""
        current = self.clock() if now is None else now
        for key, times in list(self._store.items()):
            active = [t for t in times if current - t < self.window]
            if active:
                self._store[key] = active
            else:
                del self._store[key]

        if len(self._store) > self.max_keys:
            oldest = sorted(self._store.keys(), key=lambda k: self._store[k][0])[:-self.max_keys]
            for key in oldest:
                del self._store[key]


write_limiter = SimpleRateLimiter(max_requests=10, window_seconds=1)
