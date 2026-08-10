from __future__ import annotations

import logging
from datetime import datetime
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.deps import require_admin_token
from app.core.config import get_settings
from app.core.database import get_db, get_db_no_commit
from app.schemas.admin_schemas import ConfigCreateRequest, ConfigUpsertRequest
from app.services.config_crypto import normalize_package_name
from app.services import config_service

logger = logging.getLogger(__name__)
timing_logger = logging.getLogger("uvicorn.error")


router = APIRouter(tags=["Admin - Config"], dependencies=[Depends(require_admin_token)])


@router.get("/configs")
async def list_configs(package_name: str | None = None, db: AsyncSession = Depends(get_db_no_commit)):
    try:
        normalized = normalize_package_name(package_name) if package_name else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"code": 0, "data": await config_service.list_configs(db, normalized)}


@router.get("/configs/reconcile")
async def reconcile_configs(package_name: str, db: AsyncSession = Depends(get_db_no_commit)):
    """按包名比较数据库已发布版本与下发信封版本。"""
    import httpx

    try:
        normalized = normalize_package_name(package_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    published = await config_service.get_published_config(db, normalized)
    if not published:
        return {"code": 0, "data": {"consistent": None, "message": "无有效已发布配置"}}

    # 读取包名和版本专属对象，并绕过中间缓存。
    latest_url = config_service._delivery_url(published.package_name, published.version, "main")
    cache_bust = f"?_t={int(datetime.now().timestamp())}"

    db_version = published.version
    cdn_version = None

    try:
        sdk_token = get_settings().SDK_CONFIG_TOKEN
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{latest_url}{cache_bust}",
                headers={
                    "Authorization": f"Bearer {sdk_token}",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                },
            )
            r.raise_for_status()
            cdn_data = r.json()
            cdn_version = cdn_data.get("version")
    except Exception as e:
        logger.warning("对账CDN请求失败: %s", e)
        return {"code": 0, "data": {
            "consistent": None,
            "db_version": db_version,
            "cdn_version": None,
            "message": "CDN不可达",
        }}

    consistent = (cdn_version == db_version)
    return {"code": 0, "data": {
        "consistent": consistent,
        "db_version": db_version,
        "cdn_version": cdn_version,
    }}


@router.get("/configs/{config_id}")
async def get_config_detail(config_id: int, db: AsyncSession = Depends(get_db_no_commit)):
    data = await config_service.get_config_detail(db, config_id)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="配置不存在")
    return {"code": 0, "data": data}


@router.post("/configs")
async def create_config(payload: ConfigCreateRequest, db: AsyncSession = Depends(get_db)):
    return {"code": 0, "data": await config_service.create_config(db, payload.package_name, payload.config_data, payload.change_log)}


@router.put("/configs/{config_id}")
async def update_config(
    config_id: int,
    payload: ConfigUpsertRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_no_commit),
):
    route_started = perf_counter()
    timings: dict[str, float] = {}
    try:
        data = await config_service.update_config(
            db, config_id, payload.config_data, payload.change_log, timings=timings
        )
        commit_started = perf_counter()
        await db.commit()
        timings["commit_ms"] = (perf_counter() - commit_started) * 1000
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception:
        await db.rollback()
        raise
    upload_ms = float(getattr(request.state, "request_body_read_ms", 0.0))
    timing_logger.info(
        "config_save_timing config_id=%s request_body_bytes=%s upload_ms=%.2f validation_ms=%.2f "
        "encryption_ms=%.2f db_flush_ms=%.2f db_commit_ms=%.2f total_ms=%.2f",
        config_id,
        getattr(request.state, "request_body_bytes", 0),
        upload_ms,
        timings["validation_ms"], timings["encryption_ms"], timings["flush_ms"], timings["commit_ms"],
        upload_ms + (perf_counter() - route_started) * 1000,
    )
    return {"code": 0, "data": data}


@router.post("/configs/{config_id}/publish")
async def publish_config(
    config_id: int,
    admin_user: str = Depends(require_admin_token),
    db: AsyncSession = Depends(get_db),
):
    try:
        data = await config_service.publish_config(db, config_id, admin_user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"code": 0, "data": data}


@router.post("/configs/{config_id}/rollback")
async def rollback_config(
    config_id: int,
    admin_user: str = Depends(require_admin_token),
    db: AsyncSession = Depends(get_db),
):
    try:
        data = await config_service.rollback_config(db, config_id, admin_user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"code": 0, "data": data}
