from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.deps import require_admin_token
from app.core.config import get_settings
from app.core.database import get_db, get_db_no_commit
from app.models.config import SdkConfig
from app.schemas.admin_schemas import ConfigUpsertRequest
from app.services import config_service

logger = logging.getLogger(__name__)


router = APIRouter(tags=["Admin - Config"], dependencies=[Depends(require_admin_token)])


@router.get("/configs")
async def list_configs(db: AsyncSession = Depends(get_db_no_commit)):
    return {"code": 0, "data": await config_service.list_configs(db)}


@router.get("/configs/reconcile")
async def reconcile_configs(db: AsyncSession = Depends(get_db_no_commit)):
    """对账：比较 DB published 版本与 CDN latest.json 版本号"""
    import httpx

    result = await db.execute(
        select(SdkConfig).where(
            SdkConfig.status == "published",
            SdkConfig.cos_upload_status == "success",
        ).limit(1)
    )
    published = result.scalar_one_or_none()
    if not published:
        return {"code": 0, "data": {"consistent": None, "message": "无有效已发布配置"}}

    settings = get_settings()
    # 对账读取 latest.json（非版本化对象），加缓存穿透
    latest_url = f"{settings.CDN_BASE_URL.rstrip('/')}/config/latest.json"
    cache_bust = f"?_t={int(datetime.now().timestamp())}"

    db_version = published.version
    cdn_version = None

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{latest_url}{cache_bust}",
                headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
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
async def create_config(payload: ConfigUpsertRequest, db: AsyncSession = Depends(get_db)):
    return {"code": 0, "data": await config_service.create_config(db, payload.config_data, payload.change_log)}


@router.put("/configs/{config_id}")
async def update_config(config_id: int, payload: ConfigUpsertRequest, db: AsyncSession = Depends(get_db)):
    try:
        data = await config_service.update_config(db, config_id, payload.config_data, payload.change_log)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
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
