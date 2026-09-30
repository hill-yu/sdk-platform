from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.deps import require_admin_token
from app.core.database import get_db_no_commit
from app.services import usage_duration_service
from app.services.config_crypto import normalize_package_name


router = APIRouter(
    tags=["Admin - Usage Duration"],
    dependencies=[Depends(require_admin_token)],
)


def _summary_scope(
    package_name: str | None,
    date_from: date | None,
    date_to: date | None,
    hour_from: int | None,
    hour_to: int | None,
):
    try:
        normalized_package = normalize_package_name(package_name) if package_name is not None else None
        range_start, range_end = usage_duration_service.resolve_usage_summary_range(
            date_from, date_to, hour_from, hour_to
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return normalized_package, range_start, range_end


@router.get("/usage-durations")
async def get_usage_durations(
    package_name: str | None = Query(None, min_length=1, max_length=255),
    device_id: str | None = Query(None, min_length=1, max_length=64),
    sdk_version: str | None = Query(None, min_length=1, max_length=20),
    ver: str | None = Query(None, min_length=1, max_length=50),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_no_commit),
):
    try:
        normalized_package = normalize_package_name(package_name) if package_name is not None else None
        data = await usage_duration_service.get_usage_durations(
            db,
            package_name=normalized_package,
            device_id=device_id,
            sdk_version=sdk_version,
            ver=ver,
            date_from=date_from,
            date_to=date_to,
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"code": 0, "message": "ok", "data": data}


@router.get("/usage-durations/summary")
async def get_usage_duration_summary(
    package_name: str | None = Query(None, min_length=1, max_length=255),
    date_from: date | None = Query(None),
    hour_from: int | None = Query(None, ge=0, le=23),
    date_to: date | None = Query(None),
    hour_to: int | None = Query(None, ge=0, le=23),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: str = Query("package_name", pattern="^(package_name|device_model|device_count|total_duration_s|average_duration_s|last_report_at)$"),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db_no_commit),
):
    normalized, range_start, range_end = _summary_scope(package_name, date_from, date_to, hour_from, hour_to)
    try:
        data = await usage_duration_service.get_usage_summary(
            db,
            package_name=normalized,
            range_start=range_start,
            range_end=range_end,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"code": 0, "message": "ok", "data": data}


@router.get("/usage-durations/devices")
async def get_usage_duration_devices(
    package_name: str = Query(..., min_length=1, max_length=255),
    device_model: str = Query(..., min_length=1, max_length=100),
    date_from: date | None = Query(None),
    hour_from: int | None = Query(None, ge=0, le=23),
    date_to: date | None = Query(None),
    hour_to: int | None = Query(None, ge=0, le=23),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_no_commit),
):
    normalized, range_start, range_end = _summary_scope(package_name, date_from, date_to, hour_from, hour_to)
    try:
        data = await usage_duration_service.get_usage_devices(
            db,
            package_name=normalized,
            device_model=device_model,
            range_start=range_start,
            range_end=range_end,
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"code": 0, "message": "ok", "data": data}
