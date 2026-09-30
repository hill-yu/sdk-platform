from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

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


def test_build_rows_splits_h1_and_each_pa_attempt() -> None:
    from app.models.event import SdkEvent
    from app.services.log_parse_job_service import build_h1_and_click_rows

    event = SdkEvent(
        id=11,
        event_type="log",
        package_name="com.example.app",
        device_id="device-1",
        sdk_version="2.0.0",
        server_ts=NOW,
        payload={
            "extra": (
                "H1|i=GC|p=2|pa=b11hfn1,a11sfp0||"
                "H1|i=GD|p=1|pa=w11hfn1"
            )
        },
    )

    h1_rows, click_rows, no_h1_count = build_h1_and_click_rows(event, 91)

    assert len(h1_rows) == 2
    assert len(click_rows) == 3
    assert no_h1_count == 0
    assert h1_rows[0]["declared_click_count"] == 2
    assert click_rows[0]["attempt_index"] == 1
    assert click_rows[0]["did_click"] is True
    assert click_rows[0]["navigation_code"] == 1
    assert click_rows[0]["failure_category"] is None


def test_build_rows_counts_an_event_without_h1() -> None:
    from app.models.event import SdkEvent
    from app.services.log_parse_job_service import build_h1_and_click_rows

    event = SdkEvent(
        id=12,
        event_type="log",
        package_name="com.example.app",
        server_ts=NOW,
        payload={"extra": "ordinary raw log"},
    )

    h1_rows, click_rows, no_h1_count = build_h1_and_click_rows(event, 91)

    assert h1_rows == []
    assert click_rows == []
    assert no_h1_count == 1


def test_one_bad_h1_does_not_discard_other_h1(monkeypatch) -> None:
    from app.models.event import SdkEvent
    from app.services import log_parse_job_service as service

    original = service.parse_host_final_result_line
    calls = 0

    def parse_one_at_a_time(record):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("bad H1")
        return original(record)

    monkeypatch.setattr(service, "parse_host_final_result_line", parse_one_at_a_time)
    event = SdkEvent(
        id=13,
        event_type="log",
        package_name="com.example.app",
        server_ts=NOW,
        payload={"extra": "H1|i=GC|p=1||H1|i=GD|p=2"},
    )

    h1_rows, click_rows, no_h1_count = service.build_h1_and_click_rows(event, 91)

    assert len(h1_rows) == 2
    assert h1_rows[0]["status"] == "failed"
    assert h1_rows[1]["status"] == "success"
    assert click_rows == []
    assert no_h1_count == 0


def test_failure_category_uses_reason_then_detail_then_navigation_result() -> None:
    from app.services.log_parse_job_service import choose_failure_category

    assert choose_failure_category({"navigation_code": 0, "reason": "reason-a", "error_detail": "detail-b", "navigation_result": "result-c"}) == "reason-a"
    assert choose_failure_category({"navigation_code": 0, "reason": "", "error_detail": "detail-b", "navigation_result": "result-c"}) == "detail-b"
    assert choose_failure_category({"navigation_code": 0, "reason": "", "error_detail": "", "navigation_result": "result-c"}) == "result-c"
    assert choose_failure_category({"navigation_code": 0}) == "未知原因"
    assert choose_failure_category({"navigation_code": 1, "reason": "ignored"}) is None


def test_parse_event_query_uses_snapshot_and_server_ts_event_id_cursor() -> None:
    from app.models.log_analysis import LogReparseJob
    from app.services.log_parse_job_service import build_parse_event_query

    job = LogReparseJob(
        package_name="com.example.app",
        range_start=RANGE_START,
        range_end=RANGE_END,
        snapshot_end=NOW,
        cursor_server_ts=RANGE_START,
        cursor_event_id=10,
    )

    statement = build_parse_event_query(job, batch_size=999)
    compiled = str(statement.compile(dialect=postgresql.dialect()))

    assert "sdk_events.server_ts <" in compiled
    assert "sdk_events.id >" in compiled
    assert "ORDER BY sdk_events.server_ts, sdk_events.id" in compiled
    assert statement._limit_clause.value == 200


class BatchDb:
    def __init__(self, job, events=(), *, fail_on_insert=False):
        self.job = job
        self.events = list(events)
        self.fail_on_insert = fail_on_insert
        self.statements = []
        self.nested_commits = 0
        self.flushed = 0

    class Nested:
        def __init__(self, owner):
            self.owner = owner

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            if exc_type is None:
                self.owner.nested_commits += 1
            return False

    def begin_nested(self):
        return self.Nested(self)

    async def execute(self, statement, *args, **kwargs):
        from sqlalchemy.sql import Delete, Insert, Select

        self.statements.append(statement)
        if isinstance(statement, Select):
            entity = statement.column_descriptions[0].get("entity")
            if entity is not None and entity.__name__ == "LogReparseJob":
                return Result(scalar=self.job)
            return Result(rows=self.events)
        if isinstance(statement, (Delete, Insert)):
            if self.fail_on_insert and isinstance(statement, Insert):
                raise RuntimeError("formal publish failed")
            return Result()
        raise AssertionError(statement)

    async def flush(self):
        self.flushed += 1


def test_process_batch_stages_rows_and_advances_stable_cursor() -> None:
    from app.models.event import SdkEvent
    from app.models.log_analysis import LogReparseJob
    from app.services.log_parse_job_service import process_parse_job_batch

    job = LogReparseJob(
        id=91,
        package_name="com.example.app",
        range_start=RANGE_START,
        range_end=RANGE_END,
        snapshot_end=NOW,
        status="running",
        lease_owner="worker-1",
        lease_expires_at=NOW.replace(hour=2),
        batch_size=200,
    )
    events = [
        SdkEvent(id=20, event_type="log", package_name="com.example.app", server_ts=NOW, payload={"extra": "H1|i=GC|p=1"}),
        SdkEvent(id=21, event_type="log", package_name="com.example.app", server_ts=NOW, payload={"extra": "raw"}),
    ]
    db = BatchDb(job, events)

    result = asyncio.run(process_parse_job_batch(db, 91, worker_id="worker-1", now=NOW))

    assert result.scanned == 2
    assert result.h1_count == 1
    assert result.no_h1_count == 1
    assert job.cursor_server_ts == NOW
    assert job.cursor_event_id == 21
    assert db.nested_commits == 2


def test_publish_replaces_only_job_scope_and_marks_success() -> None:
    from app.models.log_analysis import LogReparseJob
    from app.services.log_parse_job_service import publish_parse_job

    job = LogReparseJob(
        id=91,
        package_name="com.example.app",
        range_start=RANGE_START,
        range_end=RANGE_END,
        snapshot_end=NOW,
        status="running",
    )
    db = BatchDb(job)

    asyncio.run(publish_parse_job(db, job))

    assert job.status == "success"
    assert len(db.statements) == 4
    sql = "\n".join(str(statement.compile(dialect=postgresql.dialect())) for statement in db.statements)
    assert "sdk_log_click_attempts" in sql
    assert "sdk_log_h1_declarations" in sql
    assert "sdk_log_h1_declaration_stage" in sql
    assert "sdk_log_click_attempt_stage" in sql
    assert "sdk_events.server_ts >=" not in sql


def test_publish_failure_leaves_job_running_for_transaction_rollback() -> None:
    from app.models.log_analysis import LogReparseJob
    from app.services.log_parse_job_service import publish_parse_job

    job = LogReparseJob(
        id=91,
        package_name="com.example.app",
        range_start=RANGE_START,
        range_end=RANGE_END,
        snapshot_end=NOW,
        status="running",
    )

    with pytest.raises(RuntimeError, match="formal publish failed"):
        asyncio.run(publish_parse_job(BatchDb(job, fail_on_insert=True), job))

    assert job.status == "running"
