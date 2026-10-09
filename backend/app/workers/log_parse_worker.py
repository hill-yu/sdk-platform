"""Independent worker for explicit, resumable log parse jobs."""

from __future__ import annotations

import asyncio
import logging
import re
import signal
import traceback
from datetime import datetime, timezone

from app.core.database import async_session_factory
from app.services.log_parse_job_service import (
    LeaseLostError,
    MAX_PARSE_CONCURRENCY,
    MAX_PARSE_BATCH_SIZE,
    PARSE_BATCH_SIZE,
    ParseBatchResult,
    ParseExecutorPool,
    claim_parse_job,
    get_parse_job,
    mark_parse_job_failed,
    process_parse_job_batch,
    release_parse_job,
)


logger = logging.getLogger(__name__)


_SQLSTATE_RE = re.compile(r"^[0-9A-Z]{5}$")


def _exception_chain(error: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen and len(chain) < 8:
        seen.add(id(current))
        chain.append(current)
        cause = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
        if cause is None:
            cause = getattr(current, "orig", None)
        current = cause if isinstance(cause, BaseException) else None
    return chain


def _safe_exception_chain(error: BaseException) -> str:
    details = []
    for item in _exception_chain(error):
        sqlstate = getattr(item, "sqlstate", None) or getattr(item, "pgcode", None)
        if not isinstance(sqlstate, str) or not _SQLSTATE_RE.fullmatch(sqlstate):
            sqlstate = None
        details.append(
            f"{type(item).__name__}"
            + (f"[sqlstate={sqlstate}]" if sqlstate is not None else "")
        )
    return " <- ".join(details)


def _safe_traceback(error: BaseException) -> str:
    frames = []
    for index, item in enumerate(_exception_chain(error)):
        locations = " <- ".join(
            f"{frame.filename}:{frame.lineno} in {frame.name}"
            for frame in traceback.extract_tb(item.__traceback__)
        )
        if locations:
            frames.append(f"chain{index}:{locations}")
    return " || ".join(frames)


BATCH_SIZE = PARSE_BATCH_SIZE
MAX_CONCURRENCY = MAX_PARSE_CONCURRENCY
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
    job_id: int | None = None,
    now: datetime | None = None,
    stop_event: asyncio.Event | None = None,
) -> bool:
    if stop_event is not None and stop_event.is_set():
        return False
    current = now or utc_now()
    job = await claim_parse_job(db, worker_id=worker_id, now=current, job_id=job_id)
    if job is None:
        return False
    claimed_job_id = job.id
    configured_concurrency = getattr(job, "concurrency", None) or MAX_CONCURRENCY
    executor_pool = ParseExecutorPool(min(max(int(configured_concurrency), 1), MAX_CONCURRENCY))
    configured_batch_size = min(
        max(int(getattr(job, "batch_size", BATCH_SIZE) or BATCH_SIZE), 1),
        MAX_PARSE_BATCH_SIZE,
    )
    try:
        await db.commit()
        if stop_event is not None and stop_event.is_set():
            await release_parse_job(db, claimed_job_id, worker_id=worker_id, now=utc_now())
            await db.commit()
            return True
        while True:
            try:
                result: ParseBatchResult = await process_parse_job_batch(
                    db,
                    claimed_job_id,
                    worker_id=worker_id,
                    now=utc_now(),
                    batch_size=configured_batch_size,
                    executor_pool=executor_pool,
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
                logger.error(
                    "parse job failed job_id=%s error_chain=%s traceback=%s",
                    claimed_job_id,
                    _safe_exception_chain(error),
                    _safe_traceback(error),
                )
                await mark_parse_job_failed(db, claimed_job_id, error, now=utc_now())
                await db.commit()
                return True
            if result.done:
                return True
            if stop_event is not None and stop_event.is_set():
                await release_parse_job(db, claimed_job_id, worker_id=worker_id, now=utc_now())
                await db.commit()
                return True
            refreshed = await get_parse_job(db, claimed_job_id)
            if refreshed is None or refreshed.status in {"cancelled", "failed", "success"}:
                return True
    finally:
        executor_pool.shutdown()


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
