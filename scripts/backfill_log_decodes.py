"""Safely backfill decoded SDK log records in bounded, resumable batches."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import and_, delete, exists, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.timezone import business_day_utc_range  # noqa: E402
from app.models.event import SdkEvent  # noqa: E402
from app.models.log_analysis import LogDecode  # noqa: E402
from app.services.flow_log_decoder import DECODER_VERSION  # noqa: E402
from app.services.log_parse_service import (  # noqa: E402
    MAX_BATCH_SIZE,
    build_decoded_values,
    upsert_decoded_values,
)

BACKFILL_MAX_BATCH_SIZE = 500
VALID_STATUSES = frozenset({"pending", "success", "unsupported", "failed"})


@dataclass(frozen=True)
class BackfillFilters:
    date_from: date | None = None
    date_to: date | None = None
    package_name: str | None = None
    status: str | None = None
    decoder_version_before: str | None = None


@dataclass(frozen=True)
class BackfillBatchResult:
    scanned: int = 0
    success: int = 0
    unsupported: int = 0
    failed: int = 0
    last_event_id: int | None = None
    last_event_server_ts: datetime | None = None
    cumulative_scanned: int = 0
    cumulative_success: int = 0
    cumulative_unsupported: int = 0
    cumulative_failed: int = 0

    @property
    def report_line(self) -> str:
        cursor = "-"
        if self.last_event_server_ts is not None and self.last_event_id is not None:
            cursor = f"{self.last_event_server_ts.isoformat()},{self.last_event_id}"
        return (
            f"scanned={self.scanned} success={self.success} "
            f"unsupported={self.unsupported} failed={self.failed} "
            f"last_cursor={cursor} cumulative_scanned={self.cumulative_scanned} "
            f"cumulative_success={self.cumulative_success} "
            f"cumulative_unsupported={self.cumulative_unsupported} "
            f"cumulative_failed={self.cumulative_failed}"
        )


def payload_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_filters(filters: BackfillFilters) -> None:
    if (filters.date_from is None) != (filters.date_to is None):
        raise ValueError("date-from 与 date-to 必须成对提供")
    if filters.date_from is not None and filters.date_to is not None:
        if filters.date_from >= filters.date_to:
            raise ValueError("date-from 必须早于 date-to，date-to 为排他边界")
    if filters.status is not None and filters.status not in VALID_STATUSES:
        raise ValueError("status 必须是 pending/success/unsupported/failed")
    if not any(
        value is not None
        for value in (
            filters.date_from,
            filters.date_to,
            filters.package_name,
            filters.status,
            filters.decoder_version_before,
        )
    ):
        raise ValueError("必须提供至少一个范围或筛选条件，拒绝无条件全表扫描")


def validate_apply_confirmation(apply: bool, confirmation: str | None) -> None:
    if apply and confirmation != "BACKFILL_LOG_DECODES":
        raise ValueError("正式回填必须传入 --confirm BACKFILL_LOG_DECODES")


def _date_conditions(filters: BackfillFilters) -> list[Any]:
    conditions: list[Any] = []
    if filters.date_from is not None and filters.date_to is not None:
        start, _ = business_day_utc_range(filters.date_from)
        end, _ = business_day_utc_range(filters.date_to)
        conditions.extend((SdkEvent.server_ts >= start, SdkEvent.server_ts < end))
    return conditions


def build_event_query(
    filters: BackfillFilters,
    *,
    cursor_ts: datetime | None = None,
    cursor_id: int | None = None,
    batch_size: int = MAX_BATCH_SIZE,
):
    validate_filters(filters)
    if (cursor_ts is None) != (cursor_id is None):
        raise ValueError("cursor-ts 与 cursor-id 必须成对提供")
    if batch_size <= 0:
        raise ValueError("batch-size 必须为正数")
    limit = min(batch_size, BACKFILL_MAX_BATCH_SIZE)
    conditions: list[Any] = [
        SdkEvent.event_type == "log",
        text("jsonb_typeof(sdk_events.payload -> 'extra') = 'string'"),
        *_date_conditions(filters),
    ]
    if filters.package_name is not None:
        conditions.append(SdkEvent.package_name == filters.package_name)
    if filters.status is not None:
        conditions.append(
            exists(
                select(LogDecode.event_id).where(
                    LogDecode.event_id == SdkEvent.id,
                    LogDecode.event_server_ts == SdkEvent.server_ts,
                    LogDecode.status == filters.status,
                )
            )
        )
    if filters.decoder_version_before is not None:
        conditions.append(
            exists(
                select(LogDecode.event_id).where(
                    LogDecode.event_id == SdkEvent.id,
                    LogDecode.event_server_ts == SdkEvent.server_ts,
                    LogDecode.decoder_version < filters.decoder_version_before,
                )
            )
        )
    if cursor_ts is not None and cursor_id is not None:
        conditions.append(
            or_(
                SdkEvent.server_ts > cursor_ts,
                and_(SdkEvent.server_ts == cursor_ts, SdkEvent.id > cursor_id),
            )
        )
    return (
        select(SdkEvent)
        .where(*conditions)
        .order_by(SdkEvent.server_ts, SdkEvent.id)
        .limit(limit)
    )


async def process_backfill_batch(
    db: AsyncSession,
    filters: BackfillFilters,
    *,
    cursor_ts: datetime | None = None,
    cursor_id: int | None = None,
    batch_size: int = MAX_BATCH_SIZE,
    apply: bool,
    decoder_version: str = DECODER_VERSION,
) -> BackfillBatchResult:
    statement = build_event_query(
        filters,
        cursor_ts=cursor_ts,
        cursor_id=cursor_id,
        batch_size=batch_size,
    )
    result = await db.execute(statement)
    events = result.scalars().all()
    successful = unsupported = failed = 0
    last_event_id = None
    last_event_server_ts = None

    for event in events:
        original_digest = payload_sha256(event.payload)
        status, values = await build_decoded_values(
            event,
            decoder_version=decoder_version,
        )
        if apply:
            async with db.begin_nested():
                await db.execute(
                    delete(LogDecode).where(
                        LogDecode.event_id == event.id,
                        LogDecode.event_server_ts == event.server_ts,
                    )
                )
                await upsert_decoded_values(db, values)
        if payload_sha256(event.payload) != original_digest:
            raise RuntimeError("回填过程中原始payload摘要发生变化")
        if status == "success":
            successful += 1
        elif status == "unsupported":
            unsupported += 1
        else:
            failed += 1
        last_event_id = event.id
        last_event_server_ts = event.server_ts

    return BackfillBatchResult(
        scanned=len(events),
        success=successful,
        unsupported=unsupported,
        failed=failed,
        last_event_id=last_event_id,
        last_event_server_ts=last_event_server_ts,
    )


async def run_backfill(
    session_factory: Callable[[], Any],
    filters: BackfillFilters,
    *,
    apply: bool,
    batch_size: int = MAX_BATCH_SIZE,
    cursor_ts: datetime | None = None,
    cursor_id: int | None = None,
    emit: Callable[[str], None] = print,
) -> BackfillBatchResult:
    validate_filters(filters)
    if batch_size <= 0 or batch_size > BACKFILL_MAX_BATCH_SIZE:
        raise ValueError(f"batch-size 必须在 1 到 {BACKFILL_MAX_BATCH_SIZE} 之间")
    if (cursor_ts is None) != (cursor_id is None):
        raise ValueError("cursor-ts 与 cursor-id 必须成对提供")
    cumulative = BackfillBatchResult()

    while True:
        async with session_factory() as session:
            try:
                batch = await process_backfill_batch(
                    session,
                    filters,
                    cursor_ts=cursor_ts,
                    cursor_id=cursor_id,
                    batch_size=batch_size,
                    apply=apply,
                )
                if apply:
                    await session.commit()
                else:
                    await session.rollback()
            except Exception:
                await session.rollback()
                raise
        next_cursor_id = (
            batch.last_event_id
            if batch.last_event_id is not None
            else cumulative.last_event_id
        )
        next_cursor_ts = (
            batch.last_event_server_ts
            if batch.last_event_server_ts is not None
            else cumulative.last_event_server_ts
        )
        cumulative = BackfillBatchResult(
            scanned=cumulative.scanned + batch.scanned,
            success=cumulative.success + batch.success,
            unsupported=cumulative.unsupported + batch.unsupported,
            failed=cumulative.failed + batch.failed,
            last_event_id=next_cursor_id,
            last_event_server_ts=next_cursor_ts,
            cumulative_scanned=cumulative.scanned + batch.scanned,
            cumulative_success=cumulative.success + batch.success,
            cumulative_unsupported=cumulative.unsupported + batch.unsupported,
            cumulative_failed=cumulative.failed + batch.failed,
        )
        emit(
            BackfillBatchResult(
                scanned=batch.scanned,
                success=batch.success,
                unsupported=batch.unsupported,
                failed=batch.failed,
                last_event_id=next_cursor_id,
                last_event_server_ts=next_cursor_ts,
                cumulative_scanned=cumulative.scanned,
                cumulative_success=cumulative.success,
                cumulative_unsupported=cumulative.unsupported,
                cumulative_failed=cumulative.failed,
            ).report_line
        )
        if batch.scanned == 0 or batch.scanned < batch_size:
            return cumulative
        if batch.last_event_id is None or batch.last_event_server_ts is None:
            raise RuntimeError("回填批次未返回有效游标")
        cursor_ts = batch.last_event_server_ts
        cursor_id = batch.last_event_id


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value is not None else None


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("cursor-ts 必须包含时区")
    return parsed.astimezone(timezone.utc)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date-from")
    parser.add_argument("--date-to", help="排他日期边界")
    parser.add_argument("--package-name")
    parser.add_argument("--status", choices=sorted(VALID_STATUSES))
    parser.add_argument("--decoder-version-before")
    parser.add_argument("--cursor-ts")
    parser.add_argument("--cursor-id", type=int)
    parser.add_argument("--batch-size", type=int, default=MAX_BATCH_SIZE)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    filters = BackfillFilters(
        date_from=_parse_date(args.date_from),
        date_to=_parse_date(args.date_to),
        package_name=args.package_name,
        status=args.status,
        decoder_version_before=args.decoder_version_before,
    )
    validate_filters(filters)
    try:
        validate_apply_confirmation(args.apply, args.confirm)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    if (args.cursor_ts is None) != (args.cursor_id is None):
        raise SystemExit("cursor-ts 与 cursor-id 必须成对提供")
    if args.batch_size <= 0 or args.batch_size > BACKFILL_MAX_BATCH_SIZE:
        raise SystemExit(f"batch-size 必须在 1 到 {BACKFILL_MAX_BATCH_SIZE} 之间")

    from app.core.config import get_settings

    database_url = os.environ.get("DATABASE_URL") or get_settings().resolved_database_url
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        asyncio.run(
            run_backfill(
                session_factory,
                filters,
                apply=args.apply,
                batch_size=args.batch_size,
                cursor_ts=_parse_datetime(args.cursor_ts),
                cursor_id=args.cursor_id,
                emit=print,
            )
        )
    finally:
        asyncio.run(engine.dispose())


if __name__ == "__main__":
    main()
