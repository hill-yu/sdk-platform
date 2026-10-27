"""Read-only local PostgreSQL benchmark for log and usage page queries.

The database name is intentionally restricted to ``sdk_log_page_test_*`` and
the host must be loopback so this helper cannot accidentally target production.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
from datetime import datetime, timezone

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def database_url() -> str:
    value = os.environ.get("SDK_LOG_PAGE_TEST_DATABASE_URL")
    if not value:
        raise SystemExit("SDK_LOG_PAGE_TEST_DATABASE_URL is required")
    parsed = make_url(value)
    if parsed.host not in {"127.0.0.1", "::1", "localhost"} or not re.fullmatch(r"sdk_log_page_test_[0-9a-f]{4,32}", parsed.database or ""):
        raise SystemExit("refusing non-loopback or non-sdk_log_page_test_* database")
    return value


def percentile(samples: list[float], rank: float) -> float:
    values = sorted(samples)
    index = min(len(values) - 1, max(0, round((len(values) - 1) * rank)))
    return round(values[index], 2)


async def main(iterations: int) -> None:
    from app.services.analysis_service import get_event_filter_options, get_events
    from app.services.usage_duration_service import get_usage_summary

    engine = create_async_engine(database_url())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    cases = {
        "filter_options_all": lambda db: get_event_filter_options(db, package_name=None),
        "events_all_first_page": lambda db: get_events(db, page=1, page_size=20, event_type=None, log_level=None, package_name=None, sdk_version=None, device_id=None, date_from=None, date_to=None),
        "usage_summary_all": lambda db: get_usage_summary(db, package_name=None, range_start=datetime(2026, 9, 1, tzinfo=timezone.utc), range_end=datetime(2026, 10, 1, tzinfo=timezone.utc), page=1, page_size=20, sort_by="package_name", sort_order="asc"),
    }
    try:
        report = {name: [] for name in cases}
        rows = {}
        for _ in range(iterations):
            async with sessions() as session:
                for name, operation in cases.items():
                    started = time.perf_counter()
                    result = await operation(session)
                    report[name].append((time.perf_counter() - started) * 1000)
                    rows[name] = len(result.get("items", result.get("package_names", [])))
        print(json.dumps({name: {"samples": len(values), "p50_ms": percentile(values, 0.50), "p95_ms": percentile(values, 0.95), "rows": rows[name]} for name, values in report.items()}, indent=2))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=10)
    args = parser.parse_args()
    if args.iterations < 1:
        raise SystemExit("--iterations must be positive")
    asyncio.run(main(args.iterations))
