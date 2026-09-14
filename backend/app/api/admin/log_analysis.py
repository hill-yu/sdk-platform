from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.deps import require_admin_token
from app.core.database import get_db_no_commit
from app.schemas.log_analysis_schemas import (
    LogAnalysisColumnsUpdateRequest,
    PackageProfileUpdateRequest,
)
from app.services.config_crypto import normalize_package_name
from app.services import log_analysis_service

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["Admin - Log Analysis"],
    dependencies=[Depends(require_admin_token)],
)


def _normalize_package_or_422(package_name: str) -> str:
    try:
        return normalize_package_name(package_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/package-profiles", response_model=dict)
async def get_package_profile(
    package_name: str = Query(..., min_length=1, max_length=255),
    db: AsyncSession = Depends(get_db_no_commit),
):
    normalized = _normalize_package_or_422(package_name)
    try:
        data = await log_analysis_service.get_package_profile(db, normalized)
    except Exception:
        logger.exception("读取包名资料失败")
        raise HTTPException(status_code=500, detail="包名资料查询失败") from None
    return {"code": 0, "data": data}


@router.put("/package-profiles/{package_name}", response_model=dict)
async def put_package_profile(
    payload: PackageProfileUpdateRequest,
    package_name: str = Path(..., min_length=1, max_length=255),
    db: AsyncSession = Depends(get_db_no_commit),
):
    normalized = _normalize_package_or_422(package_name)
    try:
        data = await log_analysis_service.upsert_package_profile(
            db,
            normalized,
            alias=payload.alias,
            company=payload.company,
            account=payload.account,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        await db.rollback()
        logger.exception("保存包名资料失败")
        raise HTTPException(status_code=500, detail="包名资料保存失败") from None
    return {"code": 0, "data": data}


@router.get("/log-analysis/columns", response_model=dict)
async def get_log_analysis_columns(db: AsyncSession = Depends(get_db_no_commit)):
    try:
        data = await log_analysis_service.get_log_analysis_columns(db)
    except Exception:
        logger.exception("读取列配置失败")
        raise HTTPException(status_code=500, detail="列配置查询失败") from None
    return {"code": 0, "data": data}


@router.put("/log-analysis/columns", response_model=dict)
async def put_log_analysis_columns(
    payload: LogAnalysisColumnsUpdateRequest,
    db: AsyncSession = Depends(get_db_no_commit),
):
    try:
        data = await log_analysis_service.save_log_analysis_columns(db, payload.columns)
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        await db.rollback()
        logger.exception("保存列配置失败")
        raise HTTPException(status_code=500, detail="列配置保存失败") from None
    return {"code": 0, "data": data}
