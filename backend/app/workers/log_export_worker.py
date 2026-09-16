import asyncio
import logging
from pathlib import Path

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.services.log_export_service import claim_next_job, run_job

logger = logging.getLogger(__name__)


async def worker_loop() -> None:
    export_dir = Path(get_settings().LOG_EXPORT_DIR).resolve()
    while True:
        async with async_session_factory() as session:
            job = await claim_next_job(session)
        if job is None:
            await asyncio.sleep(2)
            continue
        await run_job(job.id, async_session_factory, export_dir)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(worker_loop())
