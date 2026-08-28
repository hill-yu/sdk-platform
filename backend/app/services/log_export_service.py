from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import SdkEvent
from app.models.log_export_job import LogExportJob
from app.schemas.log_export_schemas import LogExportCreateRequest

SHANGHAI = ZoneInfo("Asia/Shanghai")
CSV_HEADER = ["id", "package_name", "device_id", "sdk_version", "level", "tag", "message", "extra", "client_ts", "server_ts"]
logger = logging.getLogger(__name__)


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


def apply_job_filters(stmt, job):
    stmt = stmt.where(SdkEvent.event_type == "log", SdkEvent.package_name.in_(job.package_names))
    if job.device_id:
        stmt = stmt.where(SdkEvent.device_id == job.device_id)
    if job.log_level:
        stmt = stmt.where(SdkEvent.payload["level"].astext == job.log_level)
    if job.date_from:
        stmt = stmt.where(SdkEvent.server_ts >= datetime.combine(job.date_from, time.min, SHANGHAI))
    if job.date_to:
        stmt = stmt.where(SdkEvent.server_ts < datetime.combine(job.date_to + timedelta(days=1), time.min, SHANGHAI))
    return stmt


async def claim_next_job(db: AsyncSession) -> LogExportJob | None:
    stmt = (
        select(LogExportJob).where(LogExportJob.status == "pending")
        .order_by(LogExportJob.created_at).with_for_update(skip_locked=True).limit(1)
    )
    job = (await db.execute(stmt)).scalar_one_or_none()
    if job is None:
        return None
    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    await db.commit()
    return job


async def write_job_csv(job: LogExportJob, session_factory, export_dir: Path) -> tuple[Path, int]:
    export_dir.mkdir(parents=True, exist_ok=True)
    final_path = export_dir / f"{job.id}.csv"
    temp_path = export_dir / f"{job.id}.tmp"
    row_count = 0
    last_server_ts = None
    last_id = None
    try:
        with temp_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(CSV_HEADER)
            while True:
                stmt = apply_job_filters(select(SdkEvent), job)
                if last_server_ts is not None:
                    stmt = stmt.where(or_(
                        SdkEvent.server_ts > last_server_ts,
                        and_(SdkEvent.server_ts == last_server_ts, SdkEvent.id > last_id),
                    ))
                stmt = stmt.order_by(SdkEvent.server_ts, SdkEvent.id).limit(1000)
                async with session_factory() as session:
                    rows = (await session.execute(stmt)).scalars().all()
                for event in rows:
                    writer.writerow(csv_row_for_event(event))
                row_count += len(rows)
                if len(rows) < 1000:
                    break
                last_server_ts, last_id = rows[-1].server_ts, rows[-1].id
        temp_path.replace(final_path)
        return final_path, row_count
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


async def run_job(job_id: UUID, session_factory, export_dir: Path) -> None:
    try:
        async with session_factory() as session:
            job = await session.get(LogExportJob, job_id)
        if job is None:
            return
        file_path, row_count = await write_job_csv(job, session_factory, export_dir)
        async with session_factory() as session:
            stored = await session.get(LogExportJob, job_id)
            stored.status = "success"
            stored.file_path = str(file_path.resolve())
            stored.row_count = row_count
            stored.finished_at = datetime.now(timezone.utc)
            await session.commit()
    except Exception as exc:
        logger.exception("日志导出任务失败 job_id=%s", job_id)
        async with session_factory() as session:
            stored = await session.get(LogExportJob, job_id)
            if stored is not None:
                stored.status = "failed"
                stored.error_message = str(exc)[:1000]
                stored.finished_at = datetime.now(timezone.utc)
                await session.commit()
