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
            raise HTTPException(429, "Too many requests")
        self._store[ip].append(now)
