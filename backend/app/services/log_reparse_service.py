"""Bounded worker for queued log reparse jobs."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Integer, and_, cast, delete, exists, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.models.event import SdkEvent
from app.models.log_analysis import LogDecode, LogReparseJob
from app.services.flow_log_decoder import DECODER_VERSION
from app.services.log_analysis_service import parse_decoder_version
from app.services.log_parse_service import build_decoded_values, upsert_decoded_values

logger = logging.getLogger(__name__)
REPARSE_BATCH_SIZE = 50
REPARSE_LOOP_INTERVAL_SECONDS = 1.0


@dataclass(frozen=True)
class ReparseBatchResult:
    scanned: int = 0
    decoded: int = 0
    failed: int = 0
    done: bool = False


async def claim_pending_job(db: AsyncSession) -> LogReparseJob | None:
    job = (
        await db.execute(
            select(LogReparseJob)
            .where(LogReparseJob.status == "pending")
            .order_by(LogReparseJob.created_at, LogReparseJob.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()
    if job is not None:
        job.status = "running"
        job.error_summary = None
        await db.flush()
    return job


def _decode_version_expression(column):
    return tuple(
        cast(func.split_part(column, ".", index), Integer)
        for index in (1, 2, 3)
    )


def build_reparse_event_query(job: LogReparseJob, *, batch_size: int = REPARSE_BATCH_SIZE):
    """Build the bounded, deterministic event query for a claimed job."""
    conditions: list[Any] = [
        SdkEvent.event_type == "log",
        SdkEvent.server_ts >= job.range_start,
        SdkEvent.server_ts < job.range_end,
        text("jsonb_typeof(sdk_events.payload -> 'extra') = 'string'"),
    ]
    if job.package_name:
        conditions.append(SdkEvent.package_name == job.package_name)
    decode_key = and_(
        LogDecode.event_id == SdkEvent.id,
        LogDecode.event_server_ts == SdkEvent.server_ts,
    )
    if job.status_filter:
        conditions.append(
            exists(
                select(1).where(decode_key, LogDecode.status == job.status_filter)
            )
        )
    if job.decoder_version_before:
        version = parse_decoder_version(job.decoder_version_before)
        current = _decode_version_expression(LogDecode.decoder_version)
        version_conditions = []
        for index in range(3):
            equal_prefix = [current[p] == version[p] for p in range(index)]
            version_conditions.append(
                and_(*equal_prefix, current[index] < version[index])
            )
        conditions.append(
            exists(
                select(1).where(decode_key, or_(*version_conditions))
            )
        )
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
        .limit(min(max(batch_size, 1), REPARSE_BATCH_SIZE))
    )


async def process_reparse_job_batch(
    db: AsyncSession,
    job_id: int,
    *,
    batch_size: int = REPARSE_BATCH_SIZE,
) -> ReparseBatchResult:
    result = await db.execute(select(LogReparseJob).where(LogReparseJob.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise ValueError("重解析任务不存在")

    events = (await db.execute(build_reparse_event_query(job, batch_size=batch_size))).scalars().all()
    if not events:
        job.status = "success"
        await db.flush()
        return ReparseBatchResult(done=True)

    decoded = 0
    failed = 0
    for event in events:
        async with db.begin_nested():
            status, values = await build_decoded_values(
                event,
                decoder_version=DECODER_VERSION,
            )
            await db.execute(
                delete(LogDecode).where(
                    LogDecode.event_id == event.id,
                    LogDecode.event_server_ts == event.server_ts,
                )
            )
            await upsert_decoded_values(db, values)
        if status == "success":
            decoded += 1
        else:
            failed += 1

    last_event = events[-1]
    job.processed_count += len(events)
    job.decoded_count += decoded
    job.failed_count += failed
    job.cursor_server_ts = last_event.server_ts
    job.cursor_event_id = last_event.id
    await db.flush()
    return ReparseBatchResult(scanned=len(events), decoded=decoded, failed=failed)


def safe_job_error(error: BaseException) -> str:
    return f"{type(error).__name__}: reparse batch failed"[:512]


async def mark_reparse_job_failed(
    db: AsyncSession,
    job_id: int,
    error: BaseException,
) -> None:
    result = await db.execute(select(LogReparseJob).where(LogReparseJob.id == job_id))
    job = result.scalar_one_or_none()
    if job is not None:
        job.status = "failed"
        job.error_summary = safe_job_error(error)
        await db.flush()


async def reparse_job_loop() -> None:
    """Claim and execute reparse jobs using one transaction per batch."""
    while True:
        try:
            async with async_session_factory() as session:
                try:
                    job = await claim_pending_job(session)
                    await session.commit()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    await session.rollback()
                    raise

            if job is None:
                await asyncio.sleep(REPARSE_LOOP_INTERVAL_SECONDS)
                continue

            while True:
                try:
                    async with async_session_factory() as session:
                        result = await process_reparse_job_batch(session, job.id)
                        await session.commit()
                    if result.done:
                        break
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    async with async_session_factory() as failure_session:
                        try:
                            await mark_reparse_job_failed(failure_session, job.id, error)
                            await failure_session.commit()
                        except Exception:
                            await failure_session.rollback()
                            logger.exception("重解析任务失败状态写入失败")
                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("重解析 worker 会话失败")
            await asyncio.sleep(REPARSE_LOOP_INTERVAL_SECONDS)
