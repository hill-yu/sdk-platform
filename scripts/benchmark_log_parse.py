#!/usr/bin/env python3
"""Run a real, isolated end-to-end log parse benchmark.

The benchmark inserts controlled raw events, creates an explicit parse job,
lets the production worker process that job, and polls the persisted job until
it reaches a terminal state.  Data uses a unique benchmark package and is
removed in a finally block unless ``--keep-data`` is supplied.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import delete, insert

from app.core.database import async_session_factory, engine
from app.models.event import SdkEvent
from app.models.log_analysis import LogReparseJob
from app.models.log_metrics import (
    H1Declaration,
    H1DeclarationStage,
    LogClickAttempt,
    LogClickAttemptStage,
)
from app.services.log_parse_job_service import (
    create_parse_job,
    get_parse_job,
)
from app.workers.log_parse_worker import run_worker_once


TERMINAL_STATES = {"success", "failed", "cancelled"}
BENCHMARK_PREFIX = "__sdk_parse_benchmark__"


class BenchmarkFailure(RuntimeError):
    """Raised when the end-to-end benchmark cannot satisfy its gate."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=int, default=10_000, help="number of controlled raw events (default: 10000)")
    parser.add_argument("--max-seconds", type=float, default=60.0, help="maximum task elapsed time (default: 60)")
    parser.add_argument(
        "--package-name",
        default=None,
        help="benchmark package name; must start with __sdk_parse_benchmark__",
    )
    parser.add_argument("--keep-data", action="store_true", help="keep controlled rows for post-run inspection")
    return parser.parse_args()


def make_events(package_name: str, count: int, start: datetime) -> list[dict[str, object]]:
    payload = {"level": "info", "message": "benchmark", "extra": "controlled raw benchmark event"}
    return [
        {
            "event_type": "log",
            "package_name": package_name,
            "device_id": f"benchmark-device-{index % 32}",
            "sdk_version": "benchmark",
            "session_id": f"benchmark-session-{index % 128}",
            "payload": payload,
            "client_ts": start + timedelta(microseconds=index),
            "server_ts": start + timedelta(microseconds=index),
        }
        for index in range(count)
    ]


async def cleanup(package_name: str, job_id: int | None) -> None:
    async with async_session_factory() as session:
        if job_id is not None:
            await session.execute(delete(LogClickAttemptStage).where(LogClickAttemptStage.job_id == job_id))
            await session.execute(delete(H1DeclarationStage).where(H1DeclarationStage.job_id == job_id))
        await session.execute(delete(LogClickAttempt).where(LogClickAttempt.package_name == package_name))
        await session.execute(delete(H1Declaration).where(H1Declaration.package_name == package_name))
        await session.execute(delete(SdkEvent).where(SdkEvent.package_name == package_name))
        if job_id is not None:
            await session.execute(delete(LogReparseJob).where(LogReparseJob.id == job_id))
        await session.commit()


async def run_benchmark(args: argparse.Namespace) -> dict[str, object]:
    if args.events < 1:
        raise BenchmarkFailure("--events must be positive")
    if args.max_seconds <= 0:
        raise BenchmarkFailure("--max-seconds must be positive")

    package_name = args.package_name or f"{BENCHMARK_PREFIX}{uuid4().hex}"
    if not package_name.startswith(BENCHMARK_PREFIX):
        raise BenchmarkFailure(f"--package-name must start with {BENCHMARK_PREFIX}")

    job_id: int | None = None
    now = datetime.now(timezone.utc)
    range_start = now - timedelta(hours=1)
    range_end = now + timedelta(hours=1)
    worker_id = f"benchmark-{uuid4().hex[:24]}"

    try:
        async with async_session_factory() as session:
            await session.execute(insert(SdkEvent), make_events(package_name, args.events, range_start))
            await session.commit()

        started = perf_counter()
        async with async_session_factory() as session:
            job = await create_parse_job(
                session,
                package_name=package_name,
                range_start=range_start,
                range_end=range_end,
                now=now,
                created_by="benchmark",
            )
            await session.commit()
            job_id = int(job.id)

        async def process_job() -> None:
            async with async_session_factory() as session:
                await run_worker_once(session, worker_id=worker_id)

        worker_task = asyncio.create_task(process_job())
        job_state = None
        while True:
            elapsed = perf_counter() - started
            if elapsed > args.max_seconds:
                worker_task.cancel()
                await asyncio.gather(worker_task, return_exceptions=True)
                raise BenchmarkFailure(f"parse job exceeded {args.max_seconds:g} seconds")
            async with async_session_factory() as session:
                current = await get_parse_job(session, job_id)
                job_state = current.status if current is not None else None
            if job_state in TERMINAL_STATES:
                break
            if worker_task.done():
                await worker_task
                async with async_session_factory() as session:
                    current = await get_parse_job(session, job_id)
                    job_state = current.status if current is not None else None
                if job_state in TERMINAL_STATES:
                    break
                raise BenchmarkFailure(f"worker exited before terminal job state: {job_state or 'missing'}")
            await asyncio.sleep(0.2)

        await worker_task
        elapsed = perf_counter() - started
        async with async_session_factory() as session:
            final_job = await get_parse_job(session, job_id)
            if final_job is None:
                raise BenchmarkFailure("benchmark job disappeared")
            counts_match = (
                final_job.total_count == args.events
                and final_job.processed_count == args.events
                and final_job.failed_h1_count == 0
                and final_job.no_h1_count == args.events
            )
            passed = final_job.status == "success" and counts_match and elapsed <= args.max_seconds
            result = {
                "events": args.events,
                "elapsed_seconds": round(elapsed, 3),
                "h1_count": final_job.h1_count,
                "failed_h1_count": final_job.failed_h1_count,
                "status": final_job.status,
                "processed_count": final_job.processed_count,
                "no_h1_count": final_job.no_h1_count,
                "package_name": package_name,
                "job_id": job_id,
                "passed": passed,
            }
        if not result["passed"]:
            raise BenchmarkFailure(json.dumps(result, ensure_ascii=False))
        return result
    finally:
        if not args.keep_data:
            await cleanup(package_name, job_id)
        await engine.dispose()


def main() -> int:
    args = parse_args()
    try:
        result = asyncio.run(run_benchmark(args))
    except Exception as error:
        print(json.dumps({"events": args.events, "passed": False, "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
