"""Creation and lifecycle helpers for explicit log parse jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import and_, delete, func, insert, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.timezone import serialize_business_time
from app.models.event import SdkEvent
from app.models.log_analysis import LogReparseJob
from app.models.log_metrics import (
    H1Declaration,
    H1DeclarationStage,
    LogClickAttempt,
    LogClickAttemptStage,
)
from app.services.flow_log_decoder import DECODER_VERSION, parse_host_final_result_line
from app.services.h1_extractor import extract_h1_records


PARSE_JOB_ADVISORY_LOCK_KEY = 20260930
PARSE_BATCH_SIZE = 200
PARSE_LEASE_SECONDS = 60


class ActiveParseJobError(RuntimeError):
    """Raised when another parse job is already pending or running."""


class LeaseLostError(RuntimeError):
    """Raised when a worker no longer owns a parse job."""


@dataclass(frozen=True)
class ParseBatchResult:
    scanned: int = 0
    h1_count: int = 0
    failed_h1_count: int = 0
    no_h1_count: int = 0
    done: bool = False


def choose_failure_category(attempt: dict[str, object]) -> str | None:
    """Choose a stable failure label using the protocol's precedence order."""
    navigation_code = attempt.get("navigation_code")
    if navigation_code in (1, "1"):
        return None
    for key in ("reason", "error_detail", "navigation_result"):
        value = str(attempt.get(key) or "").strip()
        if value:
            return value
    return "未知原因"


def _event_extra(event: SdkEvent) -> str:
    payload = event.payload if isinstance(event.payload, dict) else {}
    extra = payload.get("extra")
    return extra if isinstance(extra, str) else ""


def _parse_error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: H1 parse failed"[:512]


def build_h1_and_click_rows(
    event: SdkEvent,
    job_id: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]], int]:
    """Map one raw SDK event into isolated H1 declaration and pa rows."""
    h1_rows: list[dict[str, object]] = []
    click_rows: list[dict[str, object]] = []
    records = extract_h1_records(_event_extra(event))
    for record_index, record in enumerate(records, start=1):
        base = {
            "job_id": job_id,
            "event_id": event.id,
            "event_server_ts": event.server_ts,
            "record_index": record_index,
            "package_name": event.package_name,
            "device_id": event.device_id,
            "sdk_version": event.sdk_version,
            "decoder_version": DECODER_VERSION,
        }
        try:
            decoded = asdict(parse_host_final_result_line(record))
            h1_rows.append(
                {
                    **base,
                    "config_id": decoded.get("config_id"),
                    "window": decoded.get("window"),
                    "declared_click_count": decoded.get("expected_click_count"),
                    "interstitial_presentation_count": decoded.get("interstitial_presentation_count") or 0,
                    "interstitial_click_count": decoded.get("interstitial_click_count") or 0,
                    "interstitial_close_count": decoded.get("interstitial_close_count") or 0,
                    "flow_duration_ms": decoded.get("duration_ms"),
                    "final_reason": decoded.get("final_reason"),
                    "status": "success",
                    "parse_error": None,
                    "parsed_at": datetime.now(timezone.utc),
                    "decoded_payload": decoded,
                }
            )
            for fallback_index, attempt in enumerate(decoded.get("planned_click_attempts") or [], start=1):
                attempt = dict(attempt)
                attempt_index = int(attempt.get("index") or fallback_index)
                click_rows.append(
                    {
                        **base,
                        "config_id": decoded.get("config_id"),
                        "attempt_index": attempt_index,
                        "target_kind": attempt.get("target_kind"),
                        "did_click": attempt.get("did_click"),
                        "navigation_code": attempt.get("navigation_code"),
                        "reason": attempt.get("reason"),
                        "error_detail": attempt.get("error_detail"),
                        "navigation_result": attempt.get("navigation_result"),
                        "failure_category": choose_failure_category(attempt),
                        "click_timestamp": attempt.get("click_timestamp") or None,
                        "page_context": attempt.get("page_context"),
                    }
                )
        except Exception as exc:
            h1_rows.append(
                {
                    **base,
                    "config_id": None,
                    "window": None,
                    "declared_click_count": None,
                    "interstitial_presentation_count": 0,
                    "interstitial_click_count": 0,
                    "interstitial_close_count": 0,
                    "flow_duration_ms": None,
                    "final_reason": None,
                    "status": "failed",
                    "parse_error": _parse_error(exc),
                    "parsed_at": datetime.now(timezone.utc),
                    "decoded_payload": None,
                }
            )
    return h1_rows, click_rows, 0 if records else 1


def build_parse_event_query(job: LogReparseJob, *, batch_size: int = PARSE_BATCH_SIZE):
    """Build the stable `(server_ts, event_id)` cursor query for one batch."""
    conditions: list[Any] = [
        SdkEvent.event_type == "log",
        SdkEvent.package_name == job.package_name,
        SdkEvent.server_ts >= job.range_start,
        SdkEvent.server_ts < job.snapshot_end,
    ]
    if job.cursor_server_ts is not None and job.cursor_event_id is not None:
        conditions.append(
            or_(
                SdkEvent.server_ts > job.cursor_server_ts,
                and_(
                    SdkEvent.server_ts == job.cursor_server_ts,
                    SdkEvent.id > job.cursor_event_id,
                ),
            )
        )
    return (
        select(SdkEvent)
        .where(*conditions)
        .order_by(SdkEvent.server_ts, SdkEvent.id)
        .limit(min(max(batch_size, 1), PARSE_BATCH_SIZE))
    )


def _lease_valid(job: LogReparseJob, worker_id: str, now: datetime) -> bool:
    return (
        job.status == "running"
        and job.lease_owner == worker_id
        and job.lease_expires_at is not None
        and job.lease_expires_at > now
    )


async def claim_parse_job(
    db: AsyncSession,
    *,
    worker_id: str,
    now: datetime,
) -> LogReparseJob | None:
    result = await db.execute(
        select(LogReparseJob)
        .where(LogReparseJob.status == "pending")
        .order_by(LogReparseJob.created_at, LogReparseJob.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = result.scalar_one_or_none()
    if job is None:
        return None
    job.status = "running"
    job.lease_owner = worker_id
    job.lease_expires_at = now.replace(microsecond=0)
    from datetime import timedelta

    job.lease_expires_at += timedelta(seconds=PARSE_LEASE_SECONDS)
    job.started_at = job.started_at or now
    job.last_heartbeat_at = now
    await db.flush()
    return job


async def process_parse_job_batch(
    db: AsyncSession,
    job_id: int,
    *,
    worker_id: str,
    now: datetime,
    batch_size: int = PARSE_BATCH_SIZE,
) -> ParseBatchResult:
    result = await db.execute(select(LogReparseJob).where(LogReparseJob.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise ValueError("解析任务不存在")
    if not _lease_valid(job, worker_id, now):
        raise LeaseLostError("解析任务租约已失效")

    events = (await db.execute(build_parse_event_query(job, batch_size=batch_size))).scalars().all()
    if not events:
        if job.cancel_requested_at is not None:
            job.status = "cancelled"
            job.finished_at = now
            await db.flush()
            return ParseBatchResult(done=True)
        await publish_parse_job(db, job, now=now)
        return ParseBatchResult(done=True)

    h1_count = 0
    failed_h1_count = 0
    no_h1_count = 0
    for event in events:
        if not _lease_valid(job, worker_id, now):
            raise LeaseLostError("解析任务租约已失效")
        h1_rows, click_rows, event_no_h1 = build_h1_and_click_rows(event, job.id)
        h1_count += len(h1_rows)
        failed_h1_count += sum(row["status"] == "failed" for row in h1_rows)
        no_h1_count += event_no_h1
        async with db.begin_nested():
            await db.execute(
                delete(H1DeclarationStage).where(
                    H1DeclarationStage.job_id == job.id,
                    H1DeclarationStage.event_id == event.id,
                    H1DeclarationStage.event_server_ts == event.server_ts,
                )
            )
            await db.execute(
                delete(LogClickAttemptStage).where(
                    LogClickAttemptStage.job_id == job.id,
                    LogClickAttemptStage.event_id == event.id,
                    LogClickAttemptStage.event_server_ts == event.server_ts,
                )
            )
            if h1_rows:
                await db.execute(insert(H1DeclarationStage).values(h1_rows))
            if click_rows:
                await db.execute(insert(LogClickAttemptStage).values(click_rows))

    last_event = events[-1]
    job.processed_count = (job.processed_count or 0) + len(events)
    job.h1_count = (job.h1_count or 0) + h1_count
    job.failed_h1_count = (job.failed_h1_count or 0) + failed_h1_count
    job.no_h1_count = (job.no_h1_count or 0) + no_h1_count
    job.cursor_server_ts = last_event.server_ts
    job.cursor_event_id = last_event.id
    job.last_heartbeat_at = now
    from datetime import timedelta

    job.lease_expires_at = now + timedelta(seconds=PARSE_LEASE_SECONDS)
    await db.flush()
    return ParseBatchResult(
        scanned=len(events),
        h1_count=h1_count,
        failed_h1_count=failed_h1_count,
        no_h1_count=no_h1_count,
    )


def _publish_scope(model, job: LogReparseJob):
    return and_(
        model.package_name == job.package_name,
        model.event_server_ts >= job.range_start,
        model.event_server_ts < job.snapshot_end,
    )


async def publish_parse_job(
    db: AsyncSession,
    job: LogReparseJob,
    *,
    now: datetime | None = None,
) -> None:
    """Publish staged rows; the caller commits this whole unit atomically."""
    await db.execute(delete(LogClickAttempt).where(_publish_scope(LogClickAttempt, job)))
    await db.execute(delete(H1Declaration).where(_publish_scope(H1Declaration, job)))

    h1_columns = [column.name for column in H1Declaration.__table__.columns]
    h1_stage_columns = [getattr(H1DeclarationStage, name) for name in h1_columns]
    await db.execute(
        insert(H1Declaration).from_select(
            h1_columns,
            select(*h1_stage_columns).where(H1DeclarationStage.job_id == job.id),
        )
    )
    click_columns = [column.name for column in LogClickAttempt.__table__.columns]
    click_stage_columns = [getattr(LogClickAttemptStage, name) for name in click_columns]
    await db.execute(
        insert(LogClickAttempt).from_select(
            click_columns,
            select(*click_stage_columns).where(LogClickAttemptStage.job_id == job.id),
        )
    )
    job.status = "success"
    job.finished_at = now or datetime.now(timezone.utc)
    job.lease_owner = None
    job.lease_expires_at = None
    await db.flush()


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
