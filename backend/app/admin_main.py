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
                logger.warning("ETL 刷新失败")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(etl_refresh_loop())
    try:
        yield
    finally:
        task.cancel()


cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")

app = FastAPI(title="Admin API", version="1.0.0", lifespan=lifespan, request_max_size=5_000_000)  # 5MB


@app.on_event("startup")
async def startup_admin():
    settings = get_settings()
    if not settings.ADMIN_TOKEN or settings.ADMIN_TOKEN == "admin-secret-token-change-me":
        raise RuntimeError(
            "ADMIN_TOKEN 未设置或使用弱默认值！请在 .env 中设置: ADMIN_TOKEN=<随机字符串>"
        )

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
