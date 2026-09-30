"""Creation and lifecycle helpers for explicit log parse jobs."""

from __future__ import annotations

import asyncio
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
from dataclasses import asdict, dataclass
from types import SimpleNamespace
from time import perf_counter
from typing import Any

from sqlalchemy import and_, delete, func, insert, or_, select, tuple_, update
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
PARSE_TIMEOUT_SECONDS = 1.0
PARSE_EXECUTOR_FACTORY = ProcessPoolExecutor
MAX_PARSE_CONCURRENCY = 3
PARSE_DECODE_FUNCTION = None


class ActiveParseJobError(RuntimeError):
    """Raised when another parse job is already pending or running."""


class LeaseLostError(RuntimeError):
    """Raised when a worker no longer owns a parse job."""


class ParseJobFailure(RuntimeError):
    """Raised when a parse job must enter the failed terminal state."""


class ParseExecutorPool:
    """Own one bounded process lane per executor and reuse it across batches."""

    def __init__(self, lane_count: int) -> None:
        self.executors: list[Any] = []
        self.ensure(lane_count)

    def ensure(self, lane_count: int) -> None:
        target = min(max(lane_count, 1), MAX_PARSE_CONCURRENCY)
        try:
            while len(self.executors) < target:
                self.executors.append(PARSE_EXECUTOR_FACTORY(max_workers=1))
        except BaseException:
            self.shutdown()
            raise

    def replace_lane(self, lane_index: int) -> None:
        old_executor = self.executors[lane_index]
        terminate_parse_executor(old_executor)
        self.executors[lane_index] = PARSE_EXECUTOR_FACTORY(max_workers=1)

    def shutdown(self) -> None:
        executors, self.executors = self.executors, []
        for executor in executors:
            shutdown_parse_executor(executor)


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


def event_snapshot(event: SdkEvent) -> dict[str, object]:
    """Return only serializable event data for the bounded decode executor."""
    return {
        "id": event.id,
        "event_type": event.event_type,
        "package_name": event.package_name,
        "device_id": event.device_id,
        "sdk_version": event.sdk_version,
        "server_ts": event.server_ts,
        "payload": event.payload if isinstance(event.payload, dict) else {},
    }


def build_h1_and_click_rows_from_snapshot(
    snapshot: dict[str, object], job_id: int
) -> tuple[list[dict[str, object]], list[dict[str, object]], int]:
    return build_h1_and_click_rows(SimpleNamespace(**snapshot), job_id)


def decode_snapshot_with_elapsed(
    snapshot: dict[str, object], job_id: int
) -> tuple[list[dict[str, object]], list[dict[str, object]], int, float]:
    """Decode one snapshot in a worker process and report only its own runtime."""
    started = perf_counter()
    h1_rows, click_rows, no_h1_count = build_h1_and_click_rows_from_snapshot(snapshot, job_id)
    return h1_rows, click_rows, no_h1_count, perf_counter() - started


PARSE_DECODE_FUNCTION = decode_snapshot_with_elapsed


def parse_worker_ready() -> bool:
    """Warm a lane process before starting the per-event timeout clock."""
    return True


def shutdown_parse_executor(executor: Any) -> None:
    """Always reap worker processes, including queued work on older runtimes."""
    try:
        executor.shutdown(wait=True, cancel_futures=True)
    except TypeError:
        executor.shutdown(wait=True)


def terminate_parse_executor(executor: Any) -> None:
    """Kill and join a timed-out single-worker pool before it is replaced."""
    processes = list((getattr(executor, "_processes", {}) or {}).values())
    for process in processes:
        if process.is_alive():
            killer = getattr(process, "kill", process.terminate)
            killer()
    for process in processes:
        process.join(timeout=1)
        if process.is_alive():
            process.terminate()
            process.join(timeout=1)
    shutdown_parse_executor(executor)


def _parse_error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: H1 parse failed"[:512]


def _job_error(exc: BaseException) -> str:
    if isinstance(exc, ParseJobFailure):
        return str(exc)[:512]
    return f"{type(exc).__name__}: parse job failed"[:512]


def _parse_click_timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None and value.utcoffset() is not None else None
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


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
        click_base = {key: value for key, value in base.items() if key not in {"device_id", "sdk_version"}}
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
                        **click_base,
                        "config_id": decoded.get("config_id"),
                        "attempt_index": attempt_index,
                        "target_kind": attempt.get("target_kind"),
                        "did_click": attempt.get("did_click"),
                        "navigation_code": attempt.get("navigation_code"),
                        "reason": attempt.get("reason"),
                        "error_detail": attempt.get("error_detail"),
                        "navigation_result": attempt.get("navigation_result"),
                        "failure_category": choose_failure_category(attempt),
                        "click_timestamp": _parse_click_timestamp(attempt.get("click_timestamp")),
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


def _timeout_rows(event: SdkEvent, job_id: int) -> tuple[list[dict[str, object]], list[dict[str, object]], int]:
    records = extract_h1_records(_event_extra(event))
    rows = []
    for record_index, _record in enumerate(records, start=1):
        rows.append(
            {
                "job_id": job_id,
                "event_id": event.id,
                "event_server_ts": event.server_ts,
                "record_index": record_index,
                "package_name": event.package_name,
                "device_id": event.device_id,
                "sdk_version": event.sdk_version,
                "config_id": None,
                "window": None,
                "declared_click_count": None,
                "interstitial_presentation_count": 0,
                "interstitial_click_count": 0,
                "interstitial_close_count": 0,
                "flow_duration_ms": None,
                "final_reason": None,
                "status": "failed",
                "parse_error": "TimeoutError: H1 parse timed out",
                "decoder_version": DECODER_VERSION,
                "parsed_at": datetime.now(timezone.utc),
                "decoded_payload": None,
            }
        )
    return rows, [], 0 if records else 1


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
    job_id: int | None = None,
) -> LogReparseJob | None:
    eligible = or_(
        LogReparseJob.status == "pending",
        and_(
            LogReparseJob.status == "running",
            or_(
                LogReparseJob.lease_expires_at.is_(None),
                LogReparseJob.lease_expires_at <= now,
            ),
        ),
    )
    conditions = [eligible]
    if job_id is not None:
        conditions.append(LogReparseJob.id == job_id)
    result = await db.execute(
        select(LogReparseJob)
        .where(*conditions)
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


async def clear_parse_staging(db: AsyncSession, job_id: int) -> None:
    await db.execute(delete(LogClickAttemptStage).where(LogClickAttemptStage.job_id == job_id))
    await db.execute(delete(H1DeclarationStage).where(H1DeclarationStage.job_id == job_id))


async def release_parse_job(
    db: AsyncSession,
    job_id: int,
    *,
    worker_id: str,
    now: datetime,
) -> None:
    """Return only this worker's running job to pending without changing progress."""
    await db.execute(
        update(LogReparseJob)
        .where(
            LogReparseJob.id == job_id,
            LogReparseJob.status == "running",
            LogReparseJob.lease_owner == worker_id,
        )
        .values(
            status="pending",
            lease_owner=None,
            lease_expires_at=None,
            last_heartbeat_at=now,
        )
    )
    await db.flush()


async def mark_parse_job_failed(
    db: AsyncSession,
    job_id: int,
    error: BaseException,
    *,
    now: datetime,
) -> None:
    job = await get_parse_job(db, job_id)
    if job is None:
        return
    job.status = "failed"
    job.finished_at = now
    job.error_summary = _job_error(error)
    job.lease_owner = None
    job.lease_expires_at = None
    await clear_parse_staging(db, job.id)
    await db.flush()


async def process_parse_job_batch(
    db: AsyncSession,
    job_id: int,
    *,
    worker_id: str,
    now: datetime,
    batch_size: int = PARSE_BATCH_SIZE,
    executor_pool: ParseExecutorPool | None = None,
) -> ParseBatchResult:
    result = await db.execute(select(LogReparseJob).where(LogReparseJob.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise ValueError("解析任务不存在")
    if not _lease_valid(job, worker_id, now):
        raise LeaseLostError("解析任务租约已失效")
    if job.cancel_requested_at is not None:
        job.status = "cancelled"
        job.finished_at = now
        job.lease_owner = None
        job.lease_expires_at = None
        await clear_parse_staging(db, job.id)
        await db.flush()
        return ParseBatchResult(done=True)

    events = (await db.execute(build_parse_event_query(job, batch_size=batch_size))).scalars().all()
    if not events:
        if job.cancel_requested_at is not None:
            job.status = "cancelled"
            job.finished_at = now
            job.lease_owner = None
            job.lease_expires_at = None
            await clear_parse_staging(db, job.id)
            await db.flush()
            return ParseBatchResult(done=True)
        await publish_parse_job(db, job, now=now)
        return ParseBatchResult(done=True)

    h1_count = 0
    failed_h1_count = 0
    no_h1_count = 0
    lane_count = min(max(int(job.concurrency or 1), 1), MAX_PARSE_CONCURRENCY, len(events))
    owns_executor_pool = executor_pool is None
    pool = executor_pool or ParseExecutorPool(lane_count)
    pool.ensure(lane_count)

    decoded_results: list[Any] = [None] * len(events)

    async def run_lane(lane_index: int) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(pool.executors[lane_index], parse_worker_ready)
        for event_index in range(lane_index, len(events), lane_count):
            event = events[event_index]
            try:
                decoded_results[event_index] = await asyncio.wait_for(
                    loop.run_in_executor(
                        pool.executors[lane_index],
                        PARSE_DECODE_FUNCTION,
                        event_snapshot(event),
                        job.id,
                    ),
                    timeout=PARSE_TIMEOUT_SECONDS,
                )
            except (asyncio.TimeoutError, TimeoutError) as exc:
                decoded_results[event_index] = exc
                pool.replace_lane(lane_index)
                await loop.run_in_executor(pool.executors[lane_index], parse_worker_ready)
            except Exception as exc:
                decoded_results[event_index] = exc

    try:
        lane_results = await asyncio.gather(
            *(run_lane(lane_index) for lane_index in range(lane_count)),
            return_exceptions=True,
        )
        for lane_result in lane_results:
            if isinstance(lane_result, BaseException):
                raise lane_result
    finally:
        if owns_executor_pool:
            pool.shutdown()

    event_keys = [(event.id, event.server_ts) for event in events]
    await db.execute(
        delete(H1DeclarationStage).where(
            H1DeclarationStage.job_id == job.id,
            tuple_(H1DeclarationStage.event_id, H1DeclarationStage.event_server_ts).in_(event_keys),
        )
    )
    await db.execute(
        delete(LogClickAttemptStage).where(
            LogClickAttemptStage.job_id == job.id,
            tuple_(LogClickAttemptStage.event_id, LogClickAttemptStage.event_server_ts).in_(event_keys),
        )
    )
    staged_h1_rows: list[dict[str, object]] = []
    staged_click_rows: list[dict[str, object]] = []
    for event, decoded in zip(events, decoded_results, strict=True):
        if not _lease_valid(job, worker_id, now):
            raise LeaseLostError("解析任务租约已失效")
        timeout_error: BaseException | None = None
        if isinstance(decoded, BaseException):
            if isinstance(decoded, (asyncio.TimeoutError, TimeoutError)):
                timeout_error = decoded
            else:
                raise decoded
        else:
            h1_rows, click_rows, event_no_h1, elapsed = decoded
            if elapsed > PARSE_TIMEOUT_SECONDS:
                timeout_error = TimeoutError("H1 parse timed out")
        timed_out = timeout_error is not None
        if timed_out:
            job.consecutive_timeout_count = (job.consecutive_timeout_count or 0) + 1
            h1_rows, click_rows, event_no_h1 = _timeout_rows(event, job.id)
            if job.consecutive_timeout_count >= 10:
                raise ParseJobFailure("连续超时 10 条") from timeout_error
        else:
            job.consecutive_timeout_count = 0
        h1_count += len(h1_rows)
        failed_h1_count += sum(row["status"] == "failed" for row in h1_rows)
        no_h1_count += event_no_h1
        staged_h1_rows.extend(h1_rows)
        staged_click_rows.extend(click_rows)

    if staged_h1_rows:
        await db.execute(insert(H1DeclarationStage).values(staged_h1_rows))
    if staged_click_rows:
        await db.execute(insert(LogClickAttemptStage).values(staged_click_rows))

    last_event = events[-1]
    job.processed_count = (job.processed_count or 0) + len(events)
    job.h1_count = (job.h1_count or 0) + h1_count
    job.failed_h1_count = (job.failed_h1_count or 0) + failed_h1_count
    job.no_h1_count = (job.no_h1_count or 0) + no_h1_count
    job.cursor_server_ts = last_event.server_ts
    job.cursor_event_id = last_event.id
    job.last_heartbeat_at = now
    job.lease_expires_at = now + timedelta(seconds=PARSE_LEASE_SECONDS)
    next_h1_count = job.h1_count
    next_failed_h1 = job.failed_h1_count
    if next_h1_count >= 100 and next_failed_h1 / next_h1_count > 0.2:
        raise ParseJobFailure("解析失败率超过 20%")
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
    if snapshot_end <= range_start:
        raise ValueError("snapshot_end 必须晚于 range_start")

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
        consecutive_timeout_count=0,
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
        "consecutive_timeout_count": job.consecutive_timeout_count,
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
