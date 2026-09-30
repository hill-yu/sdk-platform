from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import business_day_utc_range, business_hour_utc_range
from app.models.event import SdkEvent
from app.models.log_export_job import LogExportJob
from app.schemas.log_export_schemas import LogExportCreateRequest
from app.services.h1_extractor import extract_h1_records

SHANGHAI = ZoneInfo("Asia/Shanghai")
CSV_HEADER = ["id", "package_name", "device_id", "sdk_version", "level", "tag", "message", "extra", "client_ts", "server_ts"]
H1_CSV_HEADER = [
    "event_id", "server_time", "package_name", "device_id", "device_model", "os", "ver",
    "sdk_version", "level", "record_type", "record_index", "content",
]
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExportRow:
    event_id: int
    server_time: str
    package_name: str | None
    device_id: str | None
    device_model: str | None
    os: str | None
    ver: str | None
    sdk_version: str | None
    level: str | None
    record_type: str
    record_index: int | None
    content: str


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


def export_rows_for_event(event: SdkEvent, export_mode: str = "raw") -> list[ExportRow]:
    if export_mode not in {"raw", "h1"}:
        raise ValueError("export_mode 必须是 raw 或 h1")
    payload = event.payload if isinstance(event.payload, dict) else {}
    extra = payload.get("extra")
    if not isinstance(extra, str):
        extra = json.dumps(extra, ensure_ascii=False, separators=(",", ":")) if extra is not None else ""
    base = {
        "event_id": event.id,
        "server_time": _local_time(event.server_ts),
        "package_name": event.package_name,
        "device_id": event.device_id,
        "device_model": payload.get("device_model") or payload.get("model"),
        "os": payload.get("os"),
        "ver": payload.get("ver") or payload.get("app_version"),
        "sdk_version": event.sdk_version,
        "level": payload.get("level"),
    }
    if export_mode == "raw":
        return [ExportRow(**base, record_type="raw", record_index=None, content=extra)]
    records = extract_h1_records(extra)
    if not records:
        return [ExportRow(**base, record_type="raw", record_index=None, content=extra)]
    return [
        ExportRow(**base, record_type="h1", record_index=index, content=record)
        for index, record in enumerate(records, start=1)
    ]


def csv_row_for_export(row: ExportRow) -> list[str]:
    return [
        _csv_text(row.event_id),
        _csv_text(row.server_time),
        _csv_text(row.package_name),
        _csv_text(row.device_id),
        _csv_text(row.device_model),
        _csv_text(row.os),
        _csv_text(row.ver),
        _csv_text(row.sdk_version),
        _csv_text(row.level),
        _csv_text(row.record_type),
        _csv_text(row.record_index),
        _csv_text(row.content),
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
        "id": str(job.id), "status": job.status, "export_mode": getattr(job, "export_mode", "raw"), "row_count": int(job.row_count or 0),
        "error_message": job.error_message,
        "hour_from": getattr(job, "hour_from", None), "hour_to": getattr(job, "hour_to", None),
        "created_at": job.created_at.astimezone(SHANGHAI).isoformat(),
        "finished_at": job.finished_at.astimezone(SHANGHAI).isoformat() if job.finished_at else None,
    }


def apply_job_filters(stmt, job):
    stmt = stmt.where(SdkEvent.event_type == "log", SdkEvent.package_name.in_(job.package_names))
    if job.sdk_version:
        stmt = stmt.where(SdkEvent.sdk_version == job.sdk_version)
    if job.device_id:
        stmt = stmt.where(SdkEvent.device_id == job.device_id)
    if job.log_level:
        stmt = stmt.where(SdkEvent.payload["level"].astext == job.log_level)
    hour_from = getattr(job, "hour_from", None)
    hour_to = getattr(job, "hour_to", None)
    if job.date_from and job.date_to:
        range_start, range_end = business_hour_utc_range(job.date_from, hour_from, job.date_to, hour_to)
        stmt = stmt.where(SdkEvent.server_ts >= range_start, SdkEvent.server_ts < range_end)
    else:
        if hour_from is not None or hour_to is not None:
            raise ValueError("使用小时筛选时必须同时提供开始日期和结束日期")
        if job.date_from:
            range_start, _ = business_day_utc_range(job.date_from)
            stmt = stmt.where(SdkEvent.server_ts >= range_start)
        if job.date_to:
            _, range_end = business_day_utc_range(job.date_to)
            stmt = stmt.where(SdkEvent.server_ts < range_end)
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
            export_mode = getattr(job, "export_mode", "raw")
            writer.writerow(H1_CSV_HEADER if export_mode == "h1" else CSV_HEADER)
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
                written_rows = 0
                for event in rows:
                    if export_mode == "h1":
                        export_rows = export_rows_for_event(event, export_mode="h1")
                        for row in export_rows:
                            writer.writerow(csv_row_for_export(row))
                        written_rows += len(export_rows)
                    else:
                        writer.writerow(csv_row_for_event(event))
                        written_rows += 1
                row_count += written_rows
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
