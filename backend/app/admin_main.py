from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.admin import config_mgr, dashboard, version_mgr
from app.core.config import get_settings
from app.core.database import async_session_factory


class RequestSizeLimitMiddleware:
    """纯 ASGI 中间件：限制请求体大小，超限返回413

    策略：先缓冲全部 body，验证大小后重放给内部 app。
    Content-Length 合法时走快速路径跳过缓冲。
    """
    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # ── Content-Length 快速路径 ──
        headers = dict(scope.get("headers", []))
        cl = headers.get(b"content-length")
        if cl is not None:
            try:
                cl_int = int(cl.decode())
                if cl_int > self.max_bytes:
                    await self._send_error(send, 413, "Request body too large")
                    return
                if cl_int < 0:
                    await self._send_error(send, 400, "Invalid Content-Length")
                    return
            except (ValueError, UnicodeDecodeError):
                await self._send_error(send, 400, "Invalid Content-Length header")
                return
            # Content-Length 合法且在限制内 → 直接放行
            await self.app(scope, receive, send)
            return

        # ── 无 Content-Length（分块传输）→ 缓冲全部 body ──
        body_chunks: list[dict] = []
        total = 0

        while True:
            message = await receive()
            if message.get("type") == "http.disconnect":
                return
            if message.get("type") != "http.request":
                body_chunks.append(message)
                continue

            body = message.get("body", b"")
            total += len(body)
            if total > self.max_bytes:
                # 读完剩余 body 后返回 413
                more = message.get("more_body", False)
                while more:
                    msg = await receive()
                    more = msg.get("more_body", False)
                await self._send_error(send, 413, "Request body too large")
                return

            body_chunks.append(message)
            if not message.get("more_body", False):
                break

        # 重放缓冲的 body 给内部 app
        _iter = iter(body_chunks)

        async def replayed_receive():
            try:
                return next(_iter)
            except StopIteration:
                return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replayed_receive, send)

    async def _send_error(self, send, status: int, detail: str):
        body = f'{{"detail":"{detail}"}}'.encode()
        await send({"type": "http.response.start", "status": status,
                     "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": body})

logger = logging.getLogger(__name__)


async def etl_refresh_loop() -> None:
    """ETL 定时刷新物化视图。启动时立即刷新一次，之后每5分钟刷新。"""
    # 启动时立即刷新
    async with async_session_factory() as session:
        try:
            await session.execute(text("SELECT refresh_materialized_views()"))
            await session.commit()
            logger.info("ETL 初始刷新完成")
        except Exception:
            await session.rollback()
            logger.exception("ETL 初始刷新失败，大盘数据可能为空")

    # 定时循环
    while True:
        await asyncio.sleep(300)
        async with async_session_factory() as session:
            try:
                await session.execute(text("SELECT refresh_materialized_views()"))
                await session.commit()
            except Exception:
                await session.rollback()
                logger.exception("ETL 刷新失败")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：校验 ADMIN_TOKEN
    settings = get_settings()
    if (not settings.ADMIN_TOKEN
        or len(settings.ADMIN_TOKEN) < 32
        or "change-me" in settings.ADMIN_TOKEN.lower()
        or "admin" in settings.ADMIN_TOKEN.lower()):
        raise RuntimeError(
            "ADMIN_TOKEN 未设置或过于简单！请用 python -c \"import secrets; print(secrets.token_urlsafe(32))\" 生成强随机 Token，\n"
            "然后在 .env 中设置: ADMIN_TOKEN=<生成的token>"
        )
    logger.info("ADMIN_TOKEN 校验通过")

    if "example.com" in settings.CDN_BASE_URL or "example.com" in settings.COS_BUCKET:
        raise RuntimeError(
            "CDN/COS 配置为占位符！请在 .env 中设置真实的 CDN_BASE_URL 和 COS_BUCKET"
        )

    # 启动 ETL 定时刷新
    etl_task = asyncio.create_task(etl_refresh_loop())
    logger.info("ETL 定时刷新已启动")

    yield  # 应用运行中

    # 关闭：取消 ETL 任务
    etl_task.cancel()
    try:
        await etl_task
    except asyncio.CancelledError:
        pass


cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")

app = FastAPI(title="Admin API", version="1.0.0", lifespan=lifespan)

app.add_middleware(RequestSizeLimitMiddleware, max_bytes=5_000_000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router, prefix="/api/admin")
app.include_router(config_mgr.router, prefix="/api/admin")
app.include_router(version_mgr.router, prefix="/api/admin")


@app.get("/api/admin/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8101)
