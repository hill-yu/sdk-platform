from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.deps import require_admin_token
from app.core.database import get_db_no_commit
from app.schemas.log_analysis_schemas import (
    LogAnalysisColumnsUpdateRequest,
    LogReparseRequest,
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
        updates = {
            field: getattr(payload, field)
            for field in payload.model_fields_set
        }
        data = await log_analysis_service.upsert_package_profile(
            db,
            normalized,
            updates=updates,
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


@router.get("/log-analysis/summary", response_model=dict)
async def get_log_analysis_summary(
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    package_name: str | None = Query(None, max_length=255),
    device_id: str | None = Query(None, max_length=64),
    log_level: Literal["debug", "info", "warn", "error"] | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: str = Query(
        "date",
        pattern="^(date|package_name|user_count|flow_count|success_rate|average_duration_ms|parse_failure_count)$",
    ),
    sort_order: Literal["asc", "desc"] = Query("desc"),
    db: AsyncSession = Depends(get_db_no_commit),
):
    try:
        normalized = normalize_package_name(package_name) if package_name else None
        data = await log_analysis_service.get_log_analysis_summary(
            db,
            date_from=date_from,
            date_to=date_to,
            package_name=normalized,
            device_id=device_id,
            log_level=log_level,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        logger.exception("查询日志分析汇总失败")
        raise HTTPException(status_code=500, detail="日志分析汇总查询失败") from None
    return {"code": 0, "data": data}


@router.get("/log-analysis/details", response_model=dict)
async def get_log_analysis_details(
    date: date = Query(...),
    package_name: str = Query(..., min_length=1, max_length=255),
    device_id: str | None = Query(None, max_length=64),
    log_level: Literal["debug", "info", "warn", "error"] | None = Query(None),
    status: Literal["pending", "success", "unsupported", "failed"] | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: str = Query(
        "event_server_ts",
        pattern="^(event_server_ts|event_id|status|package_name)$",
    ),
    sort_order: Literal["asc", "desc"] = Query("desc"),
    db: AsyncSession = Depends(get_db_no_commit),
):
    try:
        normalized = normalize_package_name(package_name)
        data = await log_analysis_service.get_log_analysis_details(
            db,
            target_date=date,
            package_name=normalized,
            device_id=device_id,
            log_level=log_level,
            status=status,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        logger.exception("查询日志分析明细失败")
        raise HTTPException(status_code=500, detail="日志分析明细查询失败") from None
    return {"code": 0, "data": data}


@router.get("/log-analysis/details/{event_id}", response_model=dict)
async def get_log_analysis_detail(
    event_id: int = Path(..., ge=1),
    event_server_ts: datetime = Query(...),
    record_index: int = Query(..., ge=0),
    db: AsyncSession = Depends(get_db_no_commit),
):
    try:
        data = await log_analysis_service.get_log_analysis_detail(
            db,
            event_id=event_id,
            event_server_ts=event_server_ts,
            record_index=record_index,
        )
    except Exception:
        logger.exception("查询日志分析单条详情失败")
        raise HTTPException(status_code=500, detail="日志分析详情查询失败") from None
    if data is None:
        raise HTTPException(status_code=404, detail="日志分析详情不存在")
    return {"code": 0, "data": data}


@router.post("/log-analysis/reparse", response_model=dict)
async def create_log_reparse_job(
    payload: LogReparseRequest,
    admin_user: str = Depends(require_admin_token),
    db: AsyncSession = Depends(get_db_no_commit),
):
    raise HTTPException(
        status_code=410,
        detail="旧重解析接口已停用，请使用 /api/admin/log-analysis/parse-jobs",
    )
    try:
        data = await log_analysis_service.create_reparse_job(
            db,
            date_from=payload.date_from,
            date_to=payload.date_to,
            package_name=payload.package_name,
            status=payload.status,
            decoder_version_before=payload.decoder_version_before,
            created_by=admin_user,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        await db.rollback()
        logger.exception("创建重解析任务失败")
        raise HTTPException(status_code=500, detail="重解析任务创建失败") from None
    return {"code": 0, "data": data}
