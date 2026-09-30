"""Independent worker for explicit, resumable log parse jobs."""

from __future__ import annotations

import asyncio
import signal
from datetime import datetime, timezone

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.services.log_parse_job_service import (
    LeaseLostError,
    ParseBatchResult,
    claim_parse_job,
    get_parse_job,
    mark_parse_job_failed,
    process_parse_job_batch,
    release_parse_job,
)


BATCH_SIZE = 200
MAX_CONCURRENCY = min(get_settings().LOG_PARSE_CONCURRENCY, 3)
IDLE_SECONDS = 1.0


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def install_signal_handlers(stop_event: asyncio.Event) -> dict[int, object]:
    """Install handlers that only request a cooperative worker stop."""
    previous: dict[int, object] = {}

    def request_stop(_signum, _frame) -> None:
        stop_event.set()

    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            previous[signum] = signal.signal(signum, request_stop)
        except (OSError, ValueError):
            continue
    return previous


def restore_signal_handlers(previous: dict[int, object]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


async def run_worker_once(
    db,
    *,
    worker_id: str,
    now: datetime | None = None,
    stop_event: asyncio.Event | None = None,
) -> bool:
    if stop_event is not None and stop_event.is_set():
        return False
    current = now or utc_now()
    job = await claim_parse_job(db, worker_id=worker_id, now=current)
    if job is None:
        return False
    await db.commit()
    if stop_event is not None and stop_event.is_set():
        await release_parse_job(db, job.id, worker_id=worker_id, now=utc_now())
        await db.commit()
        return True
    while True:
        try:
            result: ParseBatchResult = await process_parse_job_batch(
                db,
                job.id,
                worker_id=worker_id,
                now=utc_now(),
                batch_size=BATCH_SIZE,
            )
            await db.commit()
        except asyncio.CancelledError:
            await db.rollback()
            raise
        except LeaseLostError:
            await db.rollback()
            return True
        except Exception as error:
            await db.rollback()
            await mark_parse_job_failed(db, job.id, error, now=utc_now())
            await db.commit()
            return True
        if result.done:
            return True
        if stop_event is not None and stop_event.is_set():
            await release_parse_job(db, job.id, worker_id=worker_id, now=utc_now())
            await db.commit()
            return True
        refreshed = await get_parse_job(db, job.id)
        if refreshed is None or refreshed.status in {"cancelled", "failed", "success"}:
            return True


async def worker_loop(*, worker_id: str, stop_event: asyncio.Event | None = None) -> None:
    event = stop_event or asyncio.Event()
    previous = install_signal_handlers(event)
    try:
        while not event.is_set():
            async with async_session_factory() as session:
                handled = await run_worker_once(session, worker_id=worker_id, stop_event=event)
            if not handled:
                try:
                    await asyncio.wait_for(event.wait(), timeout=IDLE_SECONDS)
                except asyncio.TimeoutError:
                    pass
    finally:
        restore_signal_handlers(previous)


def main() -> None:
    asyncio.run(worker_loop(worker_id="sdk-log-parse-worker"))


if __name__ == "__main__":
    main()
