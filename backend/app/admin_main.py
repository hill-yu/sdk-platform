from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.admin import config_mgr, dashboard, version_mgr
from app.core.database import engine

logger = logging.getLogger(__name__)


async def etl_refresh_loop() -> None:
    while True:
        await asyncio.sleep(300)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("SELECT refresh_materialized_views()"))
        except Exception as exc:
            logger.warning("Materialized view refresh failed: %s", exc)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(etl_refresh_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="Admin API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
