"""Read-only local PostgreSQL benchmark for log and usage page queries.

The database name is intentionally restricted to ``sdk_log_page_test_*`` and
the host must be loopback so this helper cannot accidentally target production.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import sys
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.engine import make_url
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


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
    try:
        async with sessions() as session:
            event_bounds = (await session.execute(text("SELECT min(server_ts)::date, max(server_ts)::date FROM sdk_events"))).one()
            package = (await session.execute(text("SELECT package_name FROM sdk_events WHERE event_type='log' GROUP BY package_name ORDER BY count(*) DESC LIMIT 1"))).scalar_one()
            sdk_version = (await session.execute(text("SELECT sdk_version FROM sdk_events WHERE event_type='log' AND package_name=:package AND sdk_version IS NOT NULL GROUP BY sdk_version ORDER BY count(*) DESC LIMIT 1"), {"package": package})).scalar_one()
        date_from, date_to = event_bounds
        short_start = datetime.combine(date_to, datetime.min.time(), tzinfo=timezone.utc)
        short_end = short_start + timedelta(hours=2)
        month_start = datetime.combine(max(date_from, date_to - timedelta(days=30)), datetime.min.time(), tzinfo=timezone.utc)
        month_end = datetime.combine(date_to, datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=1)
        cases = {
            "filter_options_all": lambda db: get_event_filter_options(db, package_name=None),
            "filter_options_package": lambda db: get_event_filter_options(db, package_name=package),
            "events_all_first_page": lambda db: get_events(db, page=1, page_size=20, event_type=None, log_level=None, package_name=None, sdk_version=None, device_id=None, date_from=None, date_to=None),
            "events_package_page_2": lambda db: get_events(db, page=2, page_size=20, event_type="log", log_level=None, package_name=package, sdk_version=sdk_version, device_id=None, date_from=date_from, date_to=date_to),
            "events_not_found": lambda db: get_events(db, page=1, page_size=20, event_type=None, log_level=None, package_name="com.no.such.package", sdk_version=None, device_id=None, date_from=None, date_to=None),
            "events_deep_page": lambda db: get_events(db, page=10000, page_size=20, event_type=None, log_level=None, package_name=package, sdk_version=None, device_id=None, date_from=None, date_to=None),
            "usage_summary_all": lambda db: get_usage_summary(db, package_name=None, range_start=month_start, range_end=month_end, page=1, page_size=20, sort_by="package_name", sort_order="asc"),
            "usage_summary_package": lambda db: get_usage_summary(db, package_name=package, range_start=month_start, range_end=month_end, page=1, page_size=20, sort_by="total_duration_s", sort_order="desc"),
            "usage_summary_short": lambda db: get_usage_summary(db, package_name=None, range_start=short_start, range_end=short_end, page=1, page_size=20, sort_by="package_name", sort_order="asc"),
            "usage_summary_empty": lambda db: get_usage_summary(db, package_name="com.no.such.package", range_start=month_start, range_end=month_end, page=1, page_size=20, sort_by="package_name", sort_order="asc"),
            "usage_summary_deep_page": lambda db: get_usage_summary(db, package_name=None, range_start=month_start, range_end=month_end, page=100, page_size=20, sort_by="package_name", sort_order="asc"),
        }
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
