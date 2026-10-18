from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.deps import require_admin_token
from app.core.database import get_db_no_commit
from app.models.log_metrics import H1DeclarationStage, LogClickAttemptStage
from app.schemas.log_metrics_schemas import LogParseJobCreateRequest
from app.services.log_analysis_scope import resolve_analysis_scope
from app.services import log_history_service


router = APIRouter(
    tags=["Admin - Log Metrics"],
    dependencies=[Depends(require_admin_token)],
)


def _service():
    from app.services import log_parse_job_service

    return log_parse_job_service


def _metrics_service():
    from app.services import log_metrics_service

    return log_metrics_service


def _analysis_scope(
    package_name: str = Query(..., min_length=1, max_length=255),
    date_from: date = Query(...),
    hour_from: int = Query(..., ge=0, le=23),
    date_to: date = Query(...),
    hour_to: int = Query(..., ge=0, le=23),
    snapshot_end_utc: datetime | None = Query(None),
) -> tuple[object, object, str]:
    try:
        scope = resolve_analysis_scope(
            package_name=package_name,
            date_from=date_from,
            hour_from=hour_from,
            date_to=date_to,
            hour_to=hour_to,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return scope.range_start, scope.range_end, scope.package_name


def _metric_scope(
    package_name: str = Query(..., min_length=1, max_length=255),
    date_from: date = Query(...),
    hour_from: int = Query(..., ge=0, le=23),
    date_to: date = Query(...),
    hour_to: int = Query(..., ge=0, le=23),
    snapshot_end_utc: datetime | None = Query(None),
) -> dict[str, object]:
    range_start, requested_range_end, normalized_package = _analysis_scope(
        package_name=package_name,
        date_from=date_from,
        hour_from=hour_from,
        date_to=date_to,
        hour_to=hour_to,
    )
    range_end = requested_range_end
    if snapshot_end_utc is not None:
        if snapshot_end_utc.tzinfo is None or snapshot_end_utc.utcoffset() is None:
            raise HTTPException(status_code=422, detail="snapshot_end_utc 必须包含时区")
        snapshot_end = snapshot_end_utc.astimezone(timezone.utc)
        if snapshot_end <= range_start:
            raise HTTPException(status_code=422, detail="snapshot_end_utc 必须晚于范围起点")
        if snapshot_end > requested_range_end:
            raise HTTPException(status_code=422, detail="snapshot_end_utc 不能晚于请求范围终点")
        range_end = snapshot_end
    return {
        "package_name": normalized_package,
        "range_start": range_start,
        "range_end": range_end,
    }


async def _call_metric(service_name: str, scope: dict[str, object], db: AsyncSession, **kwargs):
    try:
        return await getattr(_metrics_service(), service_name)(db, **scope, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/log-analysis/parse-jobs", response_model=dict)
async def create_parse_job(
    payload: LogParseJobCreateRequest,
    admin_user: str = Depends(require_admin_token),
    db: AsyncSession = Depends(get_db_no_commit),
):
    range_start, range_end = payload.utc_range()
    try:
        job = await _service().create_parse_job(
            db,
            package_name=payload.package_name,
            range_start=range_start,
            range_end=range_end,
            now=datetime.now(timezone.utc),
            created_by=admin_user,
        )
        await db.commit()
    except _service().ActiveParseJobError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="解析任务创建失败") from None
    return {"code": 0, "data": _service().serialize_parse_job(job)}


@router.get("/log-analysis/parse-jobs/latest", response_model=dict)
async def get_latest_parse_job(
    analysis_scope: tuple[object, object, str] = Depends(_analysis_scope),
    snapshot_end_utc: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db_no_commit),
):
    if snapshot_end_utc is not None:
        raise HTTPException(status_code=422, detail="latest 任务状态不接受 snapshot_end_utc")
    range_start, range_end, package_name = analysis_scope
    job = await _service().get_latest_parse_job(db, package_name=package_name, range_start=range_start, range_end=range_end)
    return {"code": 0, "data": _service().serialize_parse_job(job) if job is not None else None}


@router.get("/log-analysis/parse-jobs/history", response_model=dict)
async def list_historical_parse_jobs(
    package_name: str | None = Query(None, min_length=1, max_length=255),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db_no_commit),
):
    try:
        data = await log_history_service.list_parse_jobs(db, package_name=package_name, page=page, page_size=page_size)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"code": 0, "data": data}


@router.get("/log-analysis/parse-jobs/{job_id}", response_model=dict)
async def get_parse_job(
    job_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db_no_commit),
):
    job = await _service().get_parse_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="解析任务不存在")
    return {"code": 0, "data": _service().serialize_parse_job(job)}


async def _historical_scope(job_id: int, db: AsyncSession) -> dict[str, object]:
    try:
        job = await log_history_service.get_complete_job_context(db, job_id)
    except log_history_service.HistoricalParseUnavailable as exc:
        status = 404 if str(exc) == "解析任务不存在" else 409
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return {
        "package_name": job.package_name,
        "range_start": job.range_start,
        "range_end": job.snapshot_end,
        "h1_model": H1DeclarationStage,
        "click_model": LogClickAttemptStage,
        "job_id": job.id,
    }


@router.get("/log-analysis/parse-jobs/{job_id}/metrics/overview", response_model=dict)
async def get_historical_overview(job_id: int = Path(..., ge=1), db: AsyncSession = Depends(get_db_no_commit)):
    return {"code": 0, "data": await _call_metric("get_overview", await _historical_scope(job_id, db), db)}


@router.get("/log-analysis/parse-jobs/{job_id}/metrics/configs", response_model=dict)
async def get_historical_configs(job_id: int = Path(..., ge=1), db: AsyncSession = Depends(get_db_no_commit)):
    return {"code": 0, "data": await _call_metric("get_config_breakdown", await _historical_scope(job_id, db), db)}


@router.get("/log-analysis/parse-jobs/{job_id}/metrics/targets", response_model=dict)
async def get_historical_targets(job_id: int = Path(..., ge=1), db: AsyncSession = Depends(get_db_no_commit)):
    return {"code": 0, "data": await _call_metric("get_target_breakdown", await _historical_scope(job_id, db), db)}


@router.get("/log-analysis/parse-jobs/{job_id}/metrics/failures", response_model=dict)
async def get_historical_failures(
    job_id: int = Path(..., ge=1),
    target_kind: str | None = Query(None, max_length=64),
    config_id: int | None = Query(None, ge=0),
    db: AsyncSession = Depends(get_db_no_commit),
):
    return {"code": 0, "data": await _call_metric("get_failure_breakdown", await _historical_scope(job_id, db), db, target_kind=target_kind, config_id=config_id)}


@router.get("/log-analysis/parse-jobs/{job_id}/metrics/h1", response_model=dict)
async def get_historical_h1(
    job_id: int = Path(..., ge=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db_no_commit),
):
    return {"code": 0, "data": await _call_metric("get_h1_details", await _historical_scope(job_id, db), db, page=page, page_size=page_size, sort_order=sort_order)}


@router.post("/log-analysis/parse-jobs/{job_id}/cancel", response_model=dict)
async def cancel_parse_job(
    job_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db_no_commit),
):
    try:
        job = await _service().request_cancel(db, job_id)
        await db.commit()
    except LookupError as exc:
        await db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"code": 0, "data": _service().serialize_parse_job(job)}


@router.get("/log-analysis/coverage", response_model=dict)
async def get_parse_coverage(db: AsyncSession = Depends(get_db_no_commit)):
    data = await _service().get_parse_coverage(db)
    return {"code": 0, "data": data}


@router.get("/log-analysis/metrics/overview", response_model=dict)
async def get_metrics_overview(
    scope: dict[str, object] = Depends(_metric_scope),
    db: AsyncSession = Depends(get_db_no_commit),
):
    return {"code": 0, "data": await _call_metric("get_overview", scope, db)}


@router.get("/log-analysis/metrics/configs", response_model=dict)
async def get_metrics_configs(
    scope: dict[str, object] = Depends(_metric_scope),
    db: AsyncSession = Depends(get_db_no_commit),
):
    return {"code": 0, "data": await _call_metric("get_config_breakdown", scope, db)}


@router.get("/log-analysis/metrics/targets", response_model=dict)
async def get_metrics_targets(
    scope: dict[str, object] = Depends(_metric_scope),
    db: AsyncSession = Depends(get_db_no_commit),
):
    return {"code": 0, "data": await _call_metric("get_target_breakdown", scope, db)}


@router.get("/log-analysis/metrics/failures", response_model=dict)
async def get_metrics_failures(
    target_kind: str | None = Query(None, max_length=64),
    config_id: int | None = Query(None, ge=0),
    scope: dict[str, object] = Depends(_metric_scope),
    db: AsyncSession = Depends(get_db_no_commit),
):
    data = await _call_metric(
        "get_failure_breakdown",
        scope,
        db,
        target_kind=target_kind,
        config_id=config_id,
    )
    return {"code": 0, "data": data}


@router.get("/log-analysis/metrics/h1", response_model=dict)
async def get_metrics_h1(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    scope: dict[str, object] = Depends(_metric_scope),
    db: AsyncSession = Depends(get_db_no_commit),
):
    data = await _call_metric(
        "get_h1_details",
        scope,
        db,
        page=page,
        page_size=page_size,
        sort_order=sort_order,
    )
    return {"code": 0, "data": data}
