"""内存 IP 速率限制（不依赖 Redis）"""
import time
from collections import defaultdict

from fastapi import Request, HTTPException


class SimpleRateLimiter:
    def __init__(self, max_requests: int = 10, window_seconds: int = 1):
        self.max = max_requests
        self.window = window_seconds
        self._store: dict[str, list[float]] = defaultdict(list)

    async def __call__(self, request: Request):
        ip = request.client.host if request.client else "unknown"
        now = time.time()
        self._store[ip] = [t for t in self._store[ip] if now - t < self.window]
        if len(self._store[ip]) >= self.max:
            raise HTTPException(status_code=429, detail="Too many requests")
        self._store[ip].append(now)

        # 每 1000 次请求清理一次全部过期 IP
        self._cleanup_counter = getattr(self, '_cleanup_counter', 0) + 1
        if self._cleanup_counter >= 1000:
            self._cleanup_counter = 0
            # 清理所有 IP 的过期时间戳，而非仅删空列表
            for key, times in list(self._store.items()):
                active = [t for t in times if now - t < self.window]
                if active:
                    self._store[key] = active
                else:
                    del self._store[key]
            # 达到最大容量时删除最旧的键（保留最多 10000 个 IP）
            if len(self._store) > 10000:
                oldest = sorted(self._store.keys(), key=lambda k: self._store[k][0])[:-10000]
                for k in oldest:
                    del self._store[k]
