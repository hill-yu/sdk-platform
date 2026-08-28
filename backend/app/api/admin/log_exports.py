from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.deps import require_admin_token
from app.core.config import get_settings
from app.core.database import get_db, get_db_no_commit
from app.schemas.log_export_schemas import LogExportCreateRequest
from app.services import log_export_service

router = APIRouter(tags=["Admin - Log Exports"], dependencies=[Depends(require_admin_token)])


@router.get("/log-packages")
async def get_log_packages(
    keyword: str | None = Query(None, max_length=255), limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db_no_commit),
):
    return {"code": 0, "data": {"items": await log_export_service.search_packages(db, keyword, limit)}}


@router.post("/log-exports")
async def create_log_export(body: LogExportCreateRequest, db: AsyncSession = Depends(get_db)):
    return {"code": 0, "data": await log_export_service.create_job(db, body)}


@router.get("/log-exports/{job_id}")
async def get_log_export(job_id: UUID, db: AsyncSession = Depends(get_db_no_commit)):
    job = await log_export_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="导出任务不存在")
    return {"code": 0, "data": log_export_service.serialize_job(job)}


@router.get("/log-exports/{job_id}/download")
async def download_log_export(job_id: UUID, db: AsyncSession = Depends(get_db_no_commit)):
    job = await log_export_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="导出任务不存在")
    if job.status != "success":
        raise HTTPException(status_code=409, detail="导出任务尚未完成")
    export_dir = Path(get_settings().LOG_EXPORT_DIR).resolve()
    file_path = Path(job.file_path or "").resolve()
    if file_path.parent != export_dir or not file_path.is_file():
        raise HTTPException(status_code=404, detail="导出文件不存在")
    return FileResponse(file_path, media_type="text/csv; charset=utf-8", filename=f"sdk-logs-{job.id}.csv")
