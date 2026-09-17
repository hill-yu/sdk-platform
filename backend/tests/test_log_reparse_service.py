from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import Delete, Insert, Select, Update

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
        "lease_owner": reparse_service.WORKER_ID,
        "lease_expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
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
        if isinstance(statement, (Delete, Insert, Update)):
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
        if isinstance(statement, Update):
            params = statement.compile(dialect=postgresql.dialect()).params
            if "lease_expires_at" in params:
                self.job.lease_expires_at = params["lease_expires_at"]
            if "status" in params:
                self.job.status = params["status"]
            if "lease_owner" in params:
                self.job.lease_owner = params["lease_owner"]
            return _ScalarResult(None)
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


def test_claim_pending_or_expired_job_sets_stable_owner_and_ten_minute_lease():
    now = datetime(2026, 9, 17, 0, 0, tzinfo=timezone.utc)
    job = make_job(
        status="running",
        lease_owner="old-worker",
        lease_expires_at=now - timedelta(seconds=1),
        cursor_server_ts=EVENT_TS,
        cursor_event_id=10,
    )
    db = ReparseDb(job)

    claimed = asyncio.run(
        reparse_service.claim_pending_job(db, worker_id="new-worker", now=now)
    )

    assert claimed is job
    assert job.status == "running"
    assert job.lease_owner == "new-worker"
    assert job.lease_expires_at == now + timedelta(minutes=10)
    assert (job.cursor_server_ts, job.cursor_event_id) == (EVENT_TS, 10)
    sql = str(db.statements[0].compile(dialect=postgresql.dialect()))
    assert "lease_expires_at" in sql
    assert "SKIP LOCKED" in sql


def test_old_owner_cannot_process_reclaimed_job():
    job = make_job(lease_owner="new-worker")
    db = BatchDb(job=job, events=[])

    try:
        asyncio.run(
            reparse_service.process_reparse_job_batch(
                db, job.id, worker_id="old-worker"
            )
        )
    except reparse_service.LeaseLostError:
        pass
    else:
        raise AssertionError("stale owner was allowed to process the job")

    assert job.status == "running"
    assert job.lease_owner == "new-worker"


def test_success_clears_lease_after_owner_validation():
    job = make_job()
    db = BatchDb(job=job, events=[])

    result = asyncio.run(
        reparse_service.process_reparse_job_batch(
            db, job.id, worker_id=reparse_service.WORKER_ID
        )
    )

    assert result.done is True
    assert job.status == "success"
    assert job.lease_owner is None
    assert job.lease_expires_at is None


def test_renew_and_failure_clear_only_current_owner_lease():
    now = datetime(2026, 9, 17, 0, 0, tzinfo=timezone.utc)
    job = make_job(lease_owner="worker-a", lease_expires_at=now)
    db = FailureDb(job)

    renewed = asyncio.run(
        reparse_service.renew_reparse_job_lease(
            db, job.id, worker_id="worker-a", now=now
        )
    )
    assert renewed is True
    assert job.lease_expires_at == now + timedelta(minutes=10)

    asyncio.run(
        reparse_service.mark_reparse_job_failed(
            db, job.id, RuntimeError("boom"), worker_id="worker-a", now=now
        )
    )
    assert job.status == "failed"
    assert job.lease_owner is None
    assert job.lease_expires_at is None


def test_batch_rejects_lease_that_expires_before_progress_update(monkeypatch):
    start = datetime(2026, 9, 17, 0, 0, tzinfo=timezone.utc)
    expired = start + timedelta(seconds=2)
    job = make_job(lease_expires_at=start + timedelta(seconds=1))
    event = make_event(11, 1)
    db = BatchDb(job=job, events=[event])
    times = iter([start, expired])
    monkeypatch.setattr(reparse_service, "_utcnow", lambda _now=None: next(times))

    async def fake_build(_event, *, decoder_version):
        return "success", [{"event_id": 11}]

    async def fake_upsert(_db, _values):
        return None

    monkeypatch.setattr(reparse_service, "build_decoded_values", fake_build)
    monkeypatch.setattr(reparse_service, "upsert_decoded_values", fake_upsert)

    try:
        asyncio.run(reparse_service.process_reparse_job_batch(db, job.id))
    except reparse_service.LeaseLostError:
        pass
    else:
        raise AssertionError("expired lease was allowed to advance the cursor")
