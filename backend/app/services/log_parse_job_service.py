"""Creation and lifecycle helpers for explicit log parse jobs."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.timezone import serialize_business_time
from app.models.event import SdkEvent
from app.models.log_analysis import LogReparseJob


PARSE_JOB_ADVISORY_LOCK_KEY = 20260930


class ActiveParseJobError(RuntimeError):
    """Raised when another parse job is already pending or running."""


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("时间必须带时区")
    return value


async def create_parse_job(
    db: AsyncSession,
    *,
    package_name: str,
    range_start: datetime,
    range_end: datetime,
    now: datetime,
    created_by: str | None = None,
) -> LogReparseJob:
    range_start = _aware(range_start)
    range_end = _aware(range_end)
    now = _aware(now)
    if range_end <= range_start:
        raise ValueError("解析范围必须为正区间")

    settings = get_settings()
    snapshot_end = min(range_end, now)

    await db.execute(select(func.pg_advisory_xact_lock(PARSE_JOB_ADVISORY_LOCK_KEY)))
    active = await db.execute(
        select(LogReparseJob)
        .where(LogReparseJob.status.in_(["pending", "running"]))
        .with_for_update()
    )
    if active.scalars().all():
        raise ActiveParseJobError("已有解析任务正在执行")

    total_result = await db.execute(
        select(func.count(SdkEvent.id)).where(
            SdkEvent.event_type == "log",
            SdkEvent.package_name == package_name,
            SdkEvent.server_ts >= range_start,
            SdkEvent.server_ts < snapshot_end,
        )
    )
    total_count = int(total_result.scalar_one() or 0)
    job = LogReparseJob(
        package_name=package_name,
        range_start=range_start,
        range_end=range_end,
        snapshot_end=snapshot_end,
        status="pending",
        total_count=total_count,
        batch_size=settings.LOG_PARSE_BATCH_SIZE,
        concurrency=settings.LOG_PARSE_CONCURRENCY,
        processed_count=0,
        decoded_count=0,
        failed_count=0,
        h1_count=0,
        failed_h1_count=0,
        no_h1_count=0,
        created_by=created_by,
    )
    db.add(job)
    await db.flush()
    return job


async def get_parse_job(db: AsyncSession, job_id: int) -> LogReparseJob | None:
    result = await db.execute(select(LogReparseJob).where(LogReparseJob.id == job_id))
    return result.scalar_one_or_none()


async def request_cancel(
    db: AsyncSession,
    job_id: int,
    *,
    now: datetime | None = None,
) -> LogReparseJob:
    job = await get_parse_job(db, job_id)
    if job is None:
        raise LookupError("解析任务不存在")
    current = _aware(now or datetime.now(timezone.utc))
    if job.status == "pending":
        job.status = "cancelled"
        job.finished_at = current
    elif job.status == "running":
        job.cancel_requested_at = current
    await db.flush()
    return job


def serialize_parse_job(job: LogReparseJob) -> dict[str, object]:
    return {
        "id": job.id,
        "package_name": job.package_name,
        "range_start": serialize_business_time(job.range_start),
        "range_end": serialize_business_time(job.range_end),
        "snapshot_end": serialize_business_time(job.snapshot_end),
        "status": job.status,
        "total_count": job.total_count,
        "processed_count": job.processed_count,
        "decoded_count": job.decoded_count,
        "failed_count": job.failed_count,
        "h1_count": job.h1_count,
        "failed_h1_count": job.failed_h1_count,
        "no_h1_count": job.no_h1_count,
        "batch_size": job.batch_size,
        "concurrency": job.concurrency,
        "cursor_event_id": job.cursor_event_id,
        "cursor_server_ts": serialize_business_time(job.cursor_server_ts),
        "started_at": serialize_business_time(job.started_at),
        "finished_at": serialize_business_time(job.finished_at),
        "last_heartbeat_at": serialize_business_time(job.last_heartbeat_at),
        "cancel_requested_at": serialize_business_time(job.cancel_requested_at),
        "error_summary": job.error_summary,
    }


async def get_parse_coverage(db: AsyncSession) -> dict[str, int]:
    result = await db.execute(
        select(LogReparseJob.status, func.count(LogReparseJob.id)).group_by(LogReparseJob.status)
    )
    return {str(status): int(count) for status, count in result.all()}
