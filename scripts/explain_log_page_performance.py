"""Capture and explain the actual SQLAlchemy statements used by the services.

Only loopback databases named ``sdk_log_page_test_*`` are accepted. Output
redacts SQL string literals; plans are generated from the original statement
with its real bound values in the local isolated database.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def database_url() -> str:
    value = os.environ.get("SDK_LOG_PAGE_TEST_DATABASE_URL")
    configured = os.environ.get("DATABASE_URL")
    if not value or not configured:
        raise SystemExit("SDK_LOG_PAGE_TEST_DATABASE_URL and DATABASE_URL are required")
    parsed = make_url(value)
    configured_parsed = make_url(configured)
    if parsed.host not in {"127.0.0.1", "::1", "localhost"} or not re.fullmatch(r"sdk_log_page_test_[0-9a-f]{4,32}", parsed.database or ""):
        raise SystemExit("refusing non-loopback or non-sdk_log_page_test_* database")
    if (configured_parsed.host, configured_parsed.port, configured_parsed.database) != (parsed.host, parsed.port, parsed.database):
        raise SystemExit("SDK_LOG_PAGE_TEST_DATABASE_URL and DATABASE_URL must target the same database")
    return value


def redact(sql: str) -> str:
    return re.sub(r"'(?:''|[^'])*'", "'<redacted>'", sql)


def relation_names(plan: dict) -> list[str]:
    names = [plan["Relation Name"]] if plan.get("Relation Name") else []
    for child in plan.get("Plans", []):
        names.extend(relation_names(child))
    return sorted(set(names))


ALL_CAPTURED: list[object] = []


class TracingSession(AsyncSession):
    captured: list[object]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.captured = []

    async def execute(self, statement, *args, **kwargs):
        if not str(statement).startswith("EXPLAIN"):
            self.captured.append(statement)
            ALL_CAPTURED.append(statement)
        return await super().execute(statement, *args, **kwargs)


def compile_sql(statement: object) -> str:
    return str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def classify(sql: str) -> str | None:
    if "sdk_package_catalog" in sql:
        return "catalog_candidates"
    if "sdk_events" in sql and "DISTINCT" in sql and "sdk_version" in sql:
        return "sdk_versions_from_facts"
    if "sdk_events" in sql:
        return "raw_events"
    if "sdk_usage_durations" in sql and "GROUP BY" in sql:
        return "usage_summary"
    if "sdk_usage_durations" in sql:
        return "usage_devices"
    return None


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    from app.services.analysis_service import get_event_filter_options, get_events
    from app.services.usage_duration_service import get_usage_devices, get_usage_summary
    from app.services import analysis_service

    engine = create_async_engine(database_url())
    sessions = async_sessionmaker(engine, class_=TracingSession, expire_on_commit=False)
    try:
        analysis_service.async_session_factory = lambda: TracingSession(bind=engine, expire_on_commit=False)
        async with sessions() as session:
            await get_event_filter_options(session, package_name="com.ly.sixthshort")
            await get_events(
                session, page=1, page_size=20, event_type="log", log_level=None,
                package_name="com.ly.sixthshort", sdk_version="1.3.2", device_id=None,
                date_from=date(2026, 10, 18), date_to=date(2026, 10, 18), hour_from=0, hour_to=23,
            )
            await get_usage_summary(
                session, package_name=None,
                range_start=datetime(2026, 9, 18, tzinfo=timezone.utc),
                range_end=datetime(2026, 10, 19, tzinfo=timezone.utc),
                page=1, page_size=20, sort_by="package_name", sort_order="asc",
            )
            await get_usage_devices(
                session, package_name="com.ly.sixthshort", device_model=None,
                range_start=datetime(2026, 10, 18, tzinfo=timezone.utc),
                range_end=datetime(2026, 10, 19, tzinfo=timezone.utc),
                page=1, page_size=50,
            )
            statements = list(ALL_CAPTURED)

        plans = []
        async with engine.connect() as connection:
            for statement in statements:
                sql = compile_sql(statement)
                category = classify(sql)
                if category is None:
                    continue
                result = await connection.execute(text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql))
                document = result.scalar_one()
                if isinstance(document, str):
                    document = json.loads(document)
                report = document[0]
                root = report["Plan"]
                plans.append({
                    "category": category,
                    "sql_redacted": redact(sql),
                    "planning_ms": report.get("Planning Time"),
                    "execution_ms": report.get("Execution Time"),
                    "relation_names": relation_names(root),
                    "shared_hit_blocks": root.get("Shared Hit Blocks", 0),
                    "shared_read_blocks": root.get("Shared Read Blocks", 0),
                })
        print(json.dumps(plans, indent=2, ensure_ascii=False))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
