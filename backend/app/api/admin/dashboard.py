from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.deps import require_admin_token
from app.core.database import get_db, get_db_no_commit
from app.core.timezone import business_hour_utc_range, business_today
from app.services import analysis_service


router = APIRouter(tags=["Admin - Dashboard"], dependencies=[Depends(require_admin_token)])


@router.get("/dashboard/summary")
async def get_summary(db: AsyncSession = Depends(get_db_no_commit)):
    return {"code": 0, "data": await analysis_service.get_summary(db)}


@router.get("/dashboard/trend")
async def get_trend(
    range: str = Query("24h"),
    event_type: str | None = Query(None),
    db: AsyncSession = Depends(get_db_no_commit),
):
    return {"code": 0, "data": await analysis_service.get_trend(db, range, event_type)}


@router.get("/dashboard/breakdown")
async def get_breakdown(
    date_value: date | None = Query(None, alias="date"),
    dimension: str = Query("event_type"),
    db: AsyncSession = Depends(get_db_no_commit),
):
    target_date = date_value or business_today()
    return {"code": 0, "data": await analysis_service.get_breakdown(db, target_date, dimension)}


@router.get("/events")
async def get_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    event_type: str | None = Query(None),
    log_level: Literal["debug", "info", "warn", "error"] | None = Query(None),
    package_name: str | None = Query(None),
    sdk_version: str | None = Query(None),
    device_id: str | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    hour_from: int | None = Query(None, ge=0, le=23),
    hour_to: int | None = Query(None, ge=0, le=23),
    db: AsyncSession = Depends(get_db_no_commit),
):
    if (hour_from is None) != (hour_to is None):
        raise HTTPException(status_code=422, detail="hour_from 和 hour_to 必须成对提供")
    if hour_from is not None and (date_from is None or date_to is None):
        raise HTTPException(status_code=422, detail="使用小时筛选时必须同时提供开始日期和结束日期")
    if date_from is not None and date_to is not None:
        try:
            business_hour_utc_range(date_from, hour_from, date_to, hour_to)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    data = await analysis_service.get_events(
        db,
        page=page,
        page_size=page_size,
        event_type=event_type,
        log_level=log_level,
        package_name=package_name,
        sdk_version=sdk_version,
        device_id=device_id,
        date_from=date_from,
        date_to=date_to,
        hour_from=hour_from,
        hour_to=hour_to,
    )
    return {"code": 0, "data": data}


@router.get("/events/filter-options")
async def get_event_filter_options(
    package_name: str | None = Query(None),
    db: AsyncSession = Depends(get_db_no_commit),
):
    data = await analysis_service.get_event_filter_options(db, package_name=package_name)
    return {"code": 0, "data": data}
