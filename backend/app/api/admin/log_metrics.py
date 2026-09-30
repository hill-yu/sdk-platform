from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.deps import require_admin_token
from app.core.database import get_db_no_commit
from app.schemas.log_metrics_schemas import LogParseJobCreateRequest


router = APIRouter(
    tags=["Admin - Log Metrics"],
    dependencies=[Depends(require_admin_token)],
)


def _service():
    from app.services import log_parse_job_service

    return log_parse_job_service


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


@router.get("/log-analysis/parse-jobs/{job_id}", response_model=dict)
async def get_parse_job(
    job_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db_no_commit),
):
    job = await _service().get_parse_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="解析任务不存在")
    return {"code": 0, "data": _service().serialize_parse_job(job)}


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
