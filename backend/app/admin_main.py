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
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int):
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.max_bytes:
            return JSONResponse(
                status_code=413,
                content={"detail": f"Request body too large. Max: {self.max_bytes} bytes"}
            )
        return await call_next(request)

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
