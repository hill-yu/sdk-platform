from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import Delete, Insert, Select

from app.services import log_reparse_service as reparse_service
from app.services.flow_log_decoder import DECODER_VERSION

EVENT_TS = datetime(2026, 9, 16, 1, 0, tzinfo=timezone.utc)


def make_job(**overrides):
    values = {
        "id": 7,
        "package_name": "com.example.app",
        "range_start": EVENT_TS - timedelta(days=1),
        "range_end": EVENT_TS + timedelta(days=1),
        "status_filter": "failed",
        "decoder_version_before": "2.0.0",
        "cursor_server_ts": EVENT_TS,
        "cursor_event_id": 10,
        "processed_count": 0,
        "decoded_count": 0,
        "failed_count": 0,
        "status": "running",
        "error_summary": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def make_event(event_id: int, minute: int):
    return SimpleNamespace(
        id=event_id,
        server_ts=EVENT_TS + timedelta(minutes=minute),
        event_type="log",
        package_name="com.example.app",
        device_id=f"device-{event_id}",
        payload={"extra": "H1|test"},
    )


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _RowsResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows

    def scalars(self):
        return self


class _Nested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class ReparseDb:
    def __init__(self, job):
        self.job = job
        self.statements = []
        self.select_count = 0
        self.flushed = 0

    async def execute(self, statement, *args, **kwargs):
        self.statements.append(statement)
        if isinstance(statement, Select):
            self.select_count += 1
            return _ScalarResult(self.job)
        raise AssertionError(f"unexpected statement: {statement}")

    async def flush(self):
        self.flushed += 1


class BatchDb:
    def __init__(self, job, events):
        self.job = job
        self.events = events
        self.statements = []
        self.select_count = 0
        self.upserted = []
        self.flushed = 0

    async def execute(self, statement, *args, **kwargs):
        self.statements.append(statement)
        if isinstance(statement, Select):
            self.select_count += 1
            if self.select_count == 1:
                return _ScalarResult(self.job)
            return _RowsResult(self.events)
        if isinstance(statement, (Delete, Insert)):
            return _ScalarResult(None)
        raise AssertionError(f"unexpected statement: {statement}")

    def begin_nested(self):
        return _Nested()

    async def flush(self):
        self.flushed += 1


class FailureDb:
    def __init__(self, job):
        self.job = job
        self.statements = []
        self.flushed = 0

    async def execute(self, statement, *args, **kwargs):
        self.statements.append(statement)
        if isinstance(statement, Select):
            return _ScalarResult(self.job)
        raise AssertionError(f"unexpected statement: {statement}")

    async def flush(self):
        self.flushed += 1


def test_claim_pending_job_uses_skip_locked_and_marks_running():
    db = ReparseDb(make_job(status="pending"))
    job = asyncio.run(reparse_service.claim_pending_job(db))
    sql = str(db.statements[0].compile(dialect=postgresql.dialect()))

    assert "FOR UPDATE" in sql
    assert "SKIP LOCKED" in sql
    assert job.status == "running"


def test_build_query_applies_filters_and_stable_cursor():
    statement = reparse_service.build_reparse_event_query(make_job(), batch_size=50)
    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "sdk_events.server_ts >=" in sql
    assert "sdk_events.server_ts <" in sql
    assert "sdk_events.package_name =" in sql
    assert "EXISTS" in sql
    assert "split_part" in sql
    assert "sdk_events.server_ts >" in sql
    assert "sdk_events.id >" in sql
    assert "ORDER BY sdk_events.server_ts, sdk_events.id" in sql
    assert statement._limit_clause.value == 50


def test_batch_counts_success_and_unsupported_and_advances_cursor(monkeypatch):
    job = make_job(status_filter=None, decoder_version_before=None)
    first = make_event(11, 1)
    second = make_event(12, 2)
    db = BatchDb(job=job, events=[first, second])
    outcomes = iter([
        ("success", [{"event_id": 11, "event_server_ts": first.server_ts, "record_index": 0}]),
        ("unsupported", [{"event_id": 12, "event_server_ts": second.server_ts, "record_index": 0}]),
    ])

    async def fake_build(_event, *, decoder_version):
        assert decoder_version == DECODER_VERSION
        return next(outcomes)

    async def fake_upsert(_db, values):
        db.upserted.append(values)

    monkeypatch.setattr(reparse_service, "build_decoded_values", fake_build)
    monkeypatch.setattr(reparse_service, "upsert_decoded_values", fake_upsert)
    result = asyncio.run(reparse_service.process_reparse_job_batch(db, job.id))

    assert result.scanned == 2
    assert job.processed_count == 2
    assert job.decoded_count == 1
    assert job.failed_count == 1
    assert (job.cursor_server_ts, job.cursor_event_id) == (second.server_ts, 12)


def test_empty_batch_marks_job_success():
    job = make_job(cursor_server_ts=None, cursor_event_id=None)
    db = BatchDb(job=job, events=[])
    result = asyncio.run(reparse_service.process_reparse_job_batch(db, job.id))

    assert result.done is True
    assert job.status == "success"


def test_worker_failure_marks_job_failed_with_redacted_summary():
    secret = "postgres://admin:password@example.test/db RAW_EXTRA_SECRET"
    assert reparse_service.safe_job_error(RuntimeError(secret)) == "RuntimeError: reparse batch failed"
    job = make_job()
    asyncio.run(reparse_service.mark_reparse_job_failed(FailureDb(job), job.id, RuntimeError(secret)))

    assert job.status == "failed"
    assert secret not in job.error_summary
    assert "postgres://" not in job.error_summary
