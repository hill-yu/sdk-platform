"""Independent worker for explicit, resumable log parse jobs."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.services.log_parse_job_service import (
    LeaseLostError,
    ParseBatchResult,
    claim_parse_job,
    process_parse_job_batch,
)


BATCH_SIZE = 200
MAX_CONCURRENCY = min(get_settings().LOG_PARSE_CONCURRENCY, 3)
IDLE_SECONDS = 1.0


async def run_worker_once(
    db,
    *,
    worker_id: str,
    now: datetime | None = None,
) -> bool:
    current = now or datetime.now(timezone.utc)
    job = await claim_parse_job(db, worker_id=worker_id, now=current)
    if job is None:
        return False
    await db.commit()
    while True:
        try:
            result: ParseBatchResult = await process_parse_job_batch(
                db,
                job.id,
                worker_id=worker_id,
                now=current,
                batch_size=BATCH_SIZE,
            )
            await db.commit()
        except asyncio.CancelledError:
            await db.rollback()
            raise
        except LeaseLostError:
            await db.rollback()
            return True
        except Exception:
            await db.rollback()
            raise
        if result.done:
            return True


async def worker_loop(*, worker_id: str) -> None:
    while True:
        async with async_session_factory() as session:
            handled = await run_worker_once(session, worker_id=worker_id)
        if not handled:
            await asyncio.sleep(IDLE_SECONDS)


def main() -> None:
    asyncio.run(worker_loop(worker_id="sdk-log-parse-worker"))


if __name__ == "__main__":
    main()
