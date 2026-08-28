from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import SdkEvent
from app.models.log_export_job import LogExportJob
from app.schemas.log_export_schemas import LogExportCreateRequest

SHANGHAI = ZoneInfo("Asia/Shanghai")
CSV_HEADER = ["id", "package_name", "device_id", "sdk_version", "level", "tag", "message", "extra", "client_ts", "server_ts"]


def _csv_text(value: Any) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return f"'{text}" if text.startswith(("=", "+", "-", "@")) else text


def _local_time(value: datetime | None) -> str:
    return value.astimezone(SHANGHAI).strftime("%Y-%m-%d %H:%M:%S") if value else ""


def csv_row_for_event(event: SdkEvent) -> list[str]:
    payload = event.payload or {}
    return [
        str(event.id), _csv_text(event.package_name), _csv_text(event.device_id), _csv_text(event.sdk_version),
        _csv_text(payload.get("level")), _csv_text(payload.get("tag")), _csv_text(payload.get("message")),
        _csv_text(payload.get("extra")), _local_time(event.client_ts), _local_time(event.server_ts),
    ]


async def search_packages(db: AsyncSession, keyword: str | None, limit: int) -> list[str]:
    stmt = select(SdkEvent.package_name).where(SdkEvent.event_type == "log").distinct()
    if keyword and keyword.strip():
        stmt = stmt.where(SdkEvent.package_name.ilike(f"%{keyword.strip()}%"))
    rows = await db.execute(stmt.order_by(SdkEvent.package_name).limit(limit))
    return list(rows.scalars().all())


async def create_job(db: AsyncSession, body: LogExportCreateRequest) -> dict[str, str]:
    job = LogExportJob(**body.model_dump(), status="pending")
    db.add(job)
    await db.flush()
    return {"id": str(job.id), "status": job.status}


async def get_job(db: AsyncSession, job_id: UUID) -> LogExportJob | None:
    return await db.get(LogExportJob, job_id)


def serialize_job(job: LogExportJob) -> dict[str, Any]:
    return {
        "id": str(job.id), "status": job.status, "row_count": int(job.row_count or 0),
        "error_message": job.error_message,
        "created_at": job.created_at.astimezone(SHANGHAI).isoformat(),
        "finished_at": job.finished_at.astimezone(SHANGHAI).isoformat() if job.finished_at else None,
    }
