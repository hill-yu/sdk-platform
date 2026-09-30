from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import Select


RANGE_START = datetime(2026, 9, 28, 16, tzinfo=timezone.utc)
RANGE_END = datetime(2026, 10, 1, 16, tzinfo=timezone.utc)
NOW = datetime(2026, 9, 30, 1, tzinfo=timezone.utc)


class Result:
    def __init__(self, *, scalar=None, rows=()):
        self.scalar = scalar
        self.rows = list(rows)

    def scalar_one(self):
        return self.scalar

    def scalar_one_or_none(self):
        return self.scalar

    def scalars(self):
        return self

    def all(self):
        return self.rows


class JobDb:
    def __init__(self, *, active=(), total=0):
        self.active = list(active)
        self.total = total
        self.statements = []
        self.added = []
        self.flushed = False

    async def execute(self, statement, *args, **kwargs):
        self.statements.append(statement)
        sql = str(statement.compile(dialect=postgresql.dialect()))
        if "pg_advisory_xact_lock" in sql:
            return Result(scalar=None)
        if "sdk_events" in sql:
            return Result(scalar=self.total)
        if isinstance(statement, Select):
            return Result(rows=self.active)
        raise AssertionError(sql)

    def add(self, job):
        job.id = 91
        self.added.append(job)

    async def flush(self):
        self.flushed = True


def test_create_parse_job_uses_snapshot_and_counts_only_scoped_log_events() -> None:
    from app.services.log_parse_job_service import create_parse_job

    db = JobDb(total=17)
    job = asyncio.run(
        create_parse_job(
            db,
            package_name="com.example.app",
            range_start=RANGE_START,
            range_end=RANGE_END,
            now=NOW,
            created_by="admin-hash",
        )
    )

    assert job.snapshot_end == NOW
    assert job.total_count == 17
    assert job.package_name == "com.example.app"
    assert job.batch_size == 200
    assert job.concurrency == 3
    assert job.cursor_event_id is None
    assert job.cursor_server_ts is None
    assert job.processed_count == 0
    assert job.h1_count == 0
    assert job.failed_h1_count == 0
    assert job.no_h1_count == 0
    assert any("pg_advisory_xact_lock" in str(statement.compile(dialect=postgresql.dialect())) for statement in db.statements)
    assert db.flushed is True


def test_create_parse_job_rejects_an_existing_active_job() -> None:
    from app.models.log_analysis import LogReparseJob
    from app.services.log_parse_job_service import ActiveParseJobError, create_parse_job

    active = LogReparseJob(id=3, status="running")

    with pytest.raises(ActiveParseJobError):
        asyncio.run(
            create_parse_job(
                JobDb(active=[active]),
                package_name="com.example.app",
                range_start=RANGE_START,
                range_end=RANGE_END,
                now=NOW,
            )
        )


def test_serialize_parse_job_includes_snapshot_and_progress() -> None:
    from app.models.log_analysis import LogReparseJob
    from app.services.log_parse_job_service import serialize_parse_job

    job = LogReparseJob(
        id=9,
        package_name="com.example.app",
        range_start=RANGE_START,
        range_end=RANGE_END,
        snapshot_end=NOW,
        status="pending",
        total_count=17,
        batch_size=200,
        concurrency=3,
    )

    data = serialize_parse_job(job)

    assert data["snapshot_end"] == "2026-09-30T09:00:00+08:00"
    assert data["total_count"] == 17
    assert data["cursor_event_id"] is None
