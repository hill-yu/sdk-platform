from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.deps import require_admin_token
from app.core.database import get_db, get_db_no_commit
from app.models.config import SdkConfig
from app.schemas.admin_schemas import ConfigUpsertRequest
from app.services import config_service

logger = logging.getLogger(__name__)


router = APIRouter(tags=["Admin - Config"], dependencies=[Depends(require_admin_token)])


@router.get("/configs")
async def list_configs(db: AsyncSession = Depends(get_db_no_commit)):
    return {"code": 0, "data": await config_service.list_configs(db)}


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


@router.get("/configs/reconcile")
async def reconcile_configs(db: AsyncSession = Depends(get_db_no_commit)):
    """对账：比较 DB published 版本与 CDN latest.json 版本号"""
    # 查询 DB 当前 published 配置版本
    result = await db.execute(
        select(SdkConfig.version).where(SdkConfig.status == "published")
    )
    db_version = result.scalar_one_or_none() or "(无已发布配置)"

    # 尝试从 CDN 拉取 latest.json 获取版本号
    cdn_version = "(未拉取)"
    consistent = None
    try:
        import json as _json
        import urllib.request

        from app.core.config import get_settings
        settings = get_settings()
        cdn_url = f"{settings.CDN_BASE_URL.rstrip('/')}/config/latest.json"
        req = urllib.request.Request(cdn_url)
        req.add_header("Cache-Control", "no-cache")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = _json.loads(resp.read().decode())
            cdn_version = data.get("version", "(无版本字段)")
    except Exception:
        logger.warning("对账: 无法从 CDN 拉取 latest.json", exc_info=True)

    consistent = (db_version == cdn_version) if cdn_version != "(未拉取)" else None

    return {
        "code": 0,
        "data": {
            "db_version": db_version,
            "cdn_version": cdn_version,
            "consistent": consistent,
        },
    }
