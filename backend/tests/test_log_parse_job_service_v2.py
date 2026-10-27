from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import Select


RANGE_START = datetime(2026, 9, 28, 16, tzinfo=timezone.utc)
RANGE_END = datetime(2026, 10, 1, 16, tzinfo=timezone.utc)
NOW = datetime(2026, 9, 30, 1, tzinfo=timezone.utc)


def sleeping_decode_for_process_test(snapshot, _job_id):
    time.sleep(float(snapshot["payload"].get("sleep_seconds", 0)))
    return [], [], 1, 0.0


def _stage_rows(model, count: int) -> list[dict[str, object]]:
    columns = [column.name for column in model.__table__.columns]
    return [{column: index for column in columns} for index in range(count)]


def test_stage_insert_helper_splits_by_parameter_budget_and_row_cap() -> None:
    from app.models.log_metrics import H1DeclarationStage, LogClickAttemptStage
    from app.services.log_parse_job_service import _insert_stage_rows_in_chunks

    class Db:
        def __init__(self) -> None:
            self.statements = []

        async def execute(self, statement):
            self.statements.append(statement)

    db = Db()
    rows = _stage_rows(LogClickAttemptStage, 2501)

    asyncio.run(_insert_stage_rows_in_chunks(db, LogClickAttemptStage, rows))

    assert len(db.statements) == 3
    parameters = [len(statement.compile(dialect=postgresql.dialect()).params) for statement in db.statements]
    assert parameters == [17000, 17000, 8517]
    assert all(parameter_count <= 30000 for parameter_count in parameters)
    assert all(parameter_count // 17 <= 1000 for parameter_count in parameters)

    h1_db = Db()
    asyncio.run(_insert_stage_rows_in_chunks(h1_db, H1DeclarationStage, _stage_rows(H1DeclarationStage, 1001)))
    assert len(h1_db.statements) == 2
    assert [len(statement.compile(dialect=postgresql.dialect()).params) for statement in h1_db.statements] == [20000, 20]


def test_stage_insert_helper_handles_empty_and_single_row() -> None:
    from app.models.log_metrics import H1DeclarationStage
    from app.services.log_parse_job_service import _insert_stage_rows_in_chunks

    class Db:
        def __init__(self) -> None:
            self.statements = []

        async def execute(self, statement):
            self.statements.append(statement)

    db = Db()
    asyncio.run(_insert_stage_rows_in_chunks(db, H1DeclarationStage, []))
    assert db.statements == []

    asyncio.run(_insert_stage_rows_in_chunks(db, H1DeclarationStage, _stage_rows(H1DeclarationStage, 1)))
    assert len(db.statements) == 1
    assert len(db.statements[0].compile(dialect=postgresql.dialect()).params) == 20


def test_stage_insert_helper_keeps_exactly_1000_rows_in_one_chunk() -> None:
    from app.models.log_metrics import LogClickAttemptStage
    from app.services.log_parse_job_service import _insert_stage_rows_in_chunks

    class Db:
        def __init__(self) -> None:
            self.statements = []

        async def execute(self, statement):
            self.statements.append(statement)

    db = Db()
    asyncio.run(_insert_stage_rows_in_chunks(db, LogClickAttemptStage, _stage_rows(LogClickAttemptStage, 1000)))

    assert len(db.statements) == 1
    assert len(db.statements[0].compile(dialect=postgresql.dialect()).params) == 17_000


def test_stage_insert_helper_rejects_mixed_fields_without_dropping_data() -> None:
    from app.models.log_metrics import H1DeclarationStage
    from app.services.log_parse_job_service import _insert_stage_rows_in_chunks

    class Db:
        async def execute(self, _statement):
            raise AssertionError("mixed rows must be rejected before execute")

    rows = _stage_rows(H1DeclarationStage, 2)
    rows[1].pop("decoded_payload")

    with pytest.raises(ValueError, match="consistent field set"):
        asyncio.run(_insert_stage_rows_in_chunks(Db(), H1DeclarationStage, rows))


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


def test_create_parse_job_snapshots_configured_batch_and_concurrency(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.services import log_parse_job_service as service

    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: SimpleNamespace(LOG_PARSE_BATCH_SIZE=17, LOG_PARSE_CONCURRENCY=2),
    )
    job = asyncio.run(
        service.create_parse_job(
            JobDb(total=1),
            package_name="com.example.app",
            range_start=RANGE_START,
            range_end=RANGE_END,
            now=NOW,
        )
    )

    assert job.batch_size == 17
    assert job.concurrency == 2


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


def test_create_parse_job_rejects_a_fully_future_range() -> None:
    from app.services.log_parse_job_service import create_parse_job

    with pytest.raises(ValueError, match="snapshot_end"):
        asyncio.run(
            create_parse_job(
                JobDb(total=0),
                package_name="com.example.app",
                range_start=RANGE_END,
                range_end=datetime(2026, 10, 2, 16, tzinfo=timezone.utc),
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


def test_get_latest_parse_job_matches_exact_scope_and_orders_newest_first() -> None:
    from app.models.log_analysis import LogReparseJob
    from app.services.log_parse_job_service import get_latest_parse_job

    class LatestDb:
        async def execute(self, statement):
            self.statement = statement
            return Result(scalar=LogReparseJob(id=8))

    db = LatestDb()
    result = asyncio.run(
        get_latest_parse_job(
            db,
            package_name="com.example.app",
            range_start=RANGE_START,
            range_end=RANGE_END,
        )
    )

    sql = str(db.statement.compile(dialect=postgresql.dialect()))
    assert result.id == 8
    assert "sdk_log_reparse_jobs.package_name" in sql
    assert "sdk_log_reparse_jobs.range_start" in sql
    assert "sdk_log_reparse_jobs.range_end" in sql
    assert "ORDER BY sdk_log_reparse_jobs.created_at DESC, sdk_log_reparse_jobs.id DESC" in sql


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


def test_click_timestamp_is_converted_to_aware_datetime() -> None:
    from app.models.event import SdkEvent
    from app.services import log_parse_job_service as service

    summary = service.parse_host_final_result_line("H1|i=GC|p=1")
    summary.planned_click_attempts = [
        {
            "index": 1,
            "target_kind": "banner",
            "did_click": True,
            "navigation_code": 1,
            "reason": "",
            "error_detail": "",
            "navigation_result": "点击后跳转",
            "click_timestamp": "2026-09-30T09:01:02+08:00",
            "page_context": "home",
        }
    ]
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(service, "parse_host_final_result_line", lambda _record: summary)
    try:
        event = SdkEvent(
            id=14,
            event_type="log",
            package_name="com.example.app",
            server_ts=NOW,
            payload={"extra": "H1|i=GC|p=1"},
        )
        _, click_rows, _ = service.build_h1_and_click_rows(event, 91)
    finally:
        monkeypatch.undo()

    assert isinstance(click_rows[0]["click_timestamp"], datetime)
    assert click_rows[0]["click_timestamp"].tzinfo is not None


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


def test_claim_reclaims_expired_running_job_without_resetting_progress() -> None:
    from app.models.log_analysis import LogReparseJob
    from app.services.log_parse_job_service import claim_parse_job

    job = LogReparseJob(
        id=91,
        package_name="com.example.app",
        range_start=RANGE_START,
        range_end=RANGE_END,
        snapshot_end=NOW,
        status="running",
        lease_owner="dead-worker",
        lease_expires_at=NOW.replace(minute=59),
        processed_count=37,
        h1_count=40,
        failed_h1_count=2,
        no_h1_count=3,
        cursor_server_ts=NOW,
        cursor_event_id=44,
    )
    db = BatchDb(job)

    claimed = asyncio.run(
        claim_parse_job(
            db,
            worker_id="new-worker",
            now=NOW,
        )
    )

    assert claimed is job
    assert job.lease_owner == "new-worker"
    assert job.processed_count == 37
    assert job.h1_count == 40
    assert job.cursor_event_id == 44


def test_claim_uses_configured_lease_seconds(monkeypatch) -> None:
    from app.models.log_analysis import LogReparseJob
    from app.services import log_parse_job_service as service

    monkeypatch.setattr(service, "PARSE_LEASE_SECONDS", 17)
    job = LogReparseJob(
        id=91,
        package_name="com.example.app",
        range_start=RANGE_START,
        range_end=RANGE_END,
        snapshot_end=NOW,
        status="pending",
    )

    claimed = asyncio.run(service.claim_parse_job(BatchDb(job), worker_id="worker-1", now=NOW))

    assert claimed is job
    assert job.lease_expires_at == NOW + timedelta(seconds=17)


def test_release_parse_job_is_owner_scoped_and_preserves_progress() -> None:
    from app.services.log_parse_job_service import release_parse_job

    class ReleaseDb:
        def __init__(self):
            self.statements = []

        async def execute(self, statement):
            self.statements.append(statement)
            return Result()

        async def flush(self):
            pass

    db = ReleaseDb()
    asyncio.run(
        release_parse_job(
            db,
            91,
            worker_id="worker-1",
            now=NOW,
        )
    )

    sql = str(
        db.statements[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "status = 'running'" in sql
    assert "lease_owner = 'worker-1'" in sql
    assert "cursor_event_id" not in sql


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
        SdkEvent(id=20, event_type="log", package_name="com.example.app", server_ts=NOW, payload={"extra": "H1|i=GC|p=1|pa=b11hfn1"}),
        SdkEvent(id=21, event_type="log", package_name="com.example.app", server_ts=NOW, payload={"extra": "raw"}),
    ]
    db = BatchDb(job, events)

    result = asyncio.run(process_parse_job_batch(db, 91, worker_id="worker-1", now=NOW))

    assert result.scanned == 2
    assert result.h1_count == 1
    assert result.no_h1_count == 1
    assert job.cursor_server_ts == NOW
    assert job.cursor_event_id == 21
    assert db.nested_commits == 0
    stage_deletes = [statement for statement in db.statements if statement.__class__.__name__ == "Delete"]
    assert len(stage_deletes) == 2
    assert all("event_id" in str(statement.compile(dialect=postgresql.dialect())) for statement in stage_deletes)
    assert "device_id" not in db.statements[-1].compile(dialect=postgresql.dialect()).string
    assert "sdk_version" not in db.statements[-1].compile(dialect=postgresql.dialect()).string


def test_parse_executor_is_bounded_and_receives_serializable_snapshots(monkeypatch) -> None:
    from concurrent.futures import Future
    import pickle

    from app.models.event import SdkEvent
    from app.models.log_analysis import LogReparseJob
    from app.services import log_parse_job_service as service

    job = LogReparseJob(
        id=91,
        package_name="com.example.app",
        range_start=RANGE_START,
        range_end=RANGE_END,
        snapshot_end=NOW,
        status="running",
        lease_owner="worker-1",
        lease_expires_at=NOW.replace(hour=2),
        concurrency=99,
    )
    events = [
        SdkEvent(
            id=20 + index,
            event_type="log",
            package_name="com.example.app",
            server_ts=NOW,
            device_id="device-1",
            sdk_version="1.2.3",
            payload={"extra": "raw"},
        )
        for index in range(3)
    ]
    captured: dict[str, object] = {}

    class RecordingExecutor:
        def __init__(self, max_workers: int):
            captured.setdefault("max_workers", []).append(max_workers)

        def submit(self, function, *args):
            if args:
                captured.setdefault("snapshots", []).append(args[0])
            future = Future()
            future.set_result(function(*args))
            return future

        def shutdown(self, *, wait: bool, cancel_futures: bool = False):
            captured["wait"] = wait
            captured["cancel_futures"] = cancel_futures

    monkeypatch.setattr(service, "PARSE_EXECUTOR_FACTORY", RecordingExecutor)
    monkeypatch.setattr(service, "build_h1_and_click_rows_from_snapshot", lambda snapshot, job_id: ([], [], 1))

    result = asyncio.run(
        service.process_parse_job_batch(
            BatchDb(job, events),
            91,
            worker_id="worker-1",
            now=NOW,
        )
    )

    assert result.scanned == 3
    assert captured["max_workers"] == [1, 1, 1]
    assert captured["snapshots"][0] == {
        "id": 20,
        "event_type": "log",
        "package_name": "com.example.app",
        "device_id": "device-1",
        "sdk_version": "1.2.3",
        "server_ts": NOW,
        "payload": {"extra": "raw"},
    }
    pickle.dumps(captured["snapshots"][0])
    assert captured["wait"] is True
    assert captured["cancel_futures"] is True


def test_parse_executor_pool_is_reused_across_batches_and_shutdown_once(monkeypatch) -> None:
    from concurrent.futures import Future

    from app.models.event import SdkEvent
    from app.models.log_analysis import LogReparseJob
    from app.services import log_parse_job_service as service

    class RecordingExecutor:
        instances = []

        def __init__(self, max_workers: int):
            self.shutdown_calls = 0
            self.__class__.instances.append(self)

        def submit(self, function, *args):
            future = Future()
            future.set_result(function(*args))
            return future

        def shutdown(self, **kwargs):
            self.shutdown_calls += 1

    monkeypatch.setattr(service, "PARSE_EXECUTOR_FACTORY", RecordingExecutor)
    monkeypatch.setattr(service, "PARSE_DECODE_FUNCTION", lambda _snapshot, _job_id: ([], [], 1, 0.0))
    job = LogReparseJob(
        id=91,
        package_name="com.example.app",
        range_start=RANGE_START,
        range_end=RANGE_END,
        snapshot_end=NOW,
        status="running",
        lease_owner="worker-1",
        lease_expires_at=NOW.replace(hour=2),
        concurrency=2,
    )
    events = [
        SdkEvent(id=index, event_type="log", package_name="com.example.app", server_ts=NOW, payload={"extra": "raw"})
        for index in (20, 21)
    ]
    pool = service.ParseExecutorPool(2)

    asyncio.run(service.process_parse_job_batch(BatchDb(job, events), 91, worker_id="worker-1", now=NOW, executor_pool=pool))
    asyncio.run(service.process_parse_job_batch(BatchDb(job, events), 91, worker_id="worker-1", now=NOW, executor_pool=pool))

    assert len(RecordingExecutor.instances) == 2
    assert all(executor.shutdown_calls == 0 for executor in RecordingExecutor.instances)
    pool.shutdown()
    assert all(executor.shutdown_calls == 1 for executor in RecordingExecutor.instances)


def test_parse_executor_uses_bounded_waves_so_queue_wait_is_not_a_timeout(monkeypatch) -> None:
    from concurrent.futures import ThreadPoolExecutor
    import time

    from app.models.event import SdkEvent
    from app.models.log_analysis import LogReparseJob
    from app.services import log_parse_job_service as service

    monkeypatch.setattr(service, "PARSE_EXECUTOR_FACTORY", ThreadPoolExecutor)
    monkeypatch.setattr(service, "PARSE_TIMEOUT_SECONDS", 0.05)
    job = LogReparseJob(
        id=91,
        package_name="com.example.app",
        range_start=RANGE_START,
        range_end=RANGE_END,
        snapshot_end=NOW,
        status="running",
        lease_owner="worker-1",
        lease_expires_at=NOW.replace(hour=2),
        concurrency=1,
    )
    events = [
        SdkEvent(
            id=index,
            event_type="log",
            package_name="com.example.app",
            server_ts=NOW,
            payload={"extra": "raw"},
        )
        for index in (20, 21)
    ]

    def slow_but_bounded(_event, _job_id):
        time.sleep(0.04)
        return [], [], 1

    monkeypatch.setattr(service, "build_h1_and_click_rows", slow_but_bounded)
    result = asyncio.run(
        service.process_parse_job_batch(
            BatchDb(job, events),
            91,
            worker_id="worker-1",
            now=NOW,
        )
    )

    assert result.scanned == 2
    assert job.consecutive_timeout_count == 0


def test_real_process_timeout_restarts_lane_and_preserves_other_lane(monkeypatch) -> None:
    from concurrent.futures import ProcessPoolExecutor

    from app.models.event import SdkEvent
    from app.models.log_analysis import LogReparseJob
    from app.services import log_parse_job_service as service

    class TrackingProcessPool(ProcessPoolExecutor):
        instances = []

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.processes_seen = []
            self.instances.append(self)

        def shutdown(self, *args, **kwargs):
            self.processes_seen.extend((getattr(self, "_processes", {}) or {}).values())
            return super().shutdown(*args, **kwargs)

    monkeypatch.setattr(service, "PARSE_EXECUTOR_FACTORY", TrackingProcessPool)
    monkeypatch.setattr(service, "PARSE_DECODE_FUNCTION", sleeping_decode_for_process_test)
    monkeypatch.setattr(service, "PARSE_TIMEOUT_SECONDS", 0.5)
    job = LogReparseJob(
        id=91,
        package_name="com.example.app",
        range_start=RANGE_START,
        range_end=RANGE_END,
        snapshot_end=NOW,
        status="running",
        lease_owner="worker-1",
        lease_expires_at=NOW.replace(hour=2),
        concurrency=2,
    )
    events = [
        SdkEvent(
            id=20,
            event_type="log",
            package_name="com.example.app",
            server_ts=NOW,
            payload={"extra": "H1|i=GC", "sleep_seconds": 1.0},
        ),
        SdkEvent(
            id=21,
            event_type="log",
            package_name="com.example.app",
            server_ts=NOW,
            payload={"extra": "raw", "sleep_seconds": 0},
        ),
    ]

    started = time.perf_counter()
    result = asyncio.run(
        service.process_parse_job_batch(
            BatchDb(job, events),
            91,
            worker_id="worker-1",
            now=NOW,
        )
    )
    elapsed = time.perf_counter() - started

    assert elapsed < 3
    assert result.scanned == 2
    assert result.h1_count == 1
    assert result.failed_h1_count == 1
    assert job.cursor_event_id == 21
    assert len(TrackingProcessPool.instances) == 3
    assert all(pool._max_workers == 1 for pool in TrackingProcessPool.instances)
    assert all(not process.is_alive() for pool in TrackingProcessPool.instances for process in pool.processes_seen)


def test_cancel_requested_between_batches_stops_before_scanning_or_publishing() -> None:
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
        cancel_requested_at=NOW,
    )
    db = BatchDb(job, events=[object()])

    result = asyncio.run(process_parse_job_batch(db, 91, worker_id="worker-1", now=NOW))

    assert result.done is True
    assert job.status == "cancelled"
    assert job.finished_at == NOW
    assert job.lease_owner is None
    assert not any("sdk_events" in str(statement) for statement in db.statements)


def test_ten_consecutive_timeouts_fail_the_job(monkeypatch) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from app.models.event import SdkEvent
    from app.models.log_analysis import LogReparseJob
    from app.services import log_parse_job_service as service

    monkeypatch.setattr(service, "PARSE_EXECUTOR_FACTORY", ThreadPoolExecutor)

    job = LogReparseJob(
        id=91,
        package_name="com.example.app",
        range_start=RANGE_START,
        range_end=RANGE_END,
        snapshot_end=NOW,
        status="running",
        lease_owner="worker-1",
        lease_expires_at=NOW.replace(hour=2),
        consecutive_timeout_count=0,
    )
    events = [
        SdkEvent(id=index, event_type="log", package_name="com.example.app", server_ts=NOW, payload={"extra": "H1|i=GC"})
        for index in range(10)
    ]

    def timeout(_event, _job_id):
        raise TimeoutError("secret payload")

    monkeypatch.setattr(service, "build_h1_and_click_rows", timeout)

    with pytest.raises(service.ParseJobFailure, match="连续超时"):
        asyncio.run(
            service.process_parse_job_batch(
                BatchDb(job, events),
                91,
                worker_id="worker-1",
                now=NOW,
            )
        )


def test_actual_decoder_elapsed_time_counts_as_a_timeout(monkeypatch) -> None:
    from concurrent.futures import ThreadPoolExecutor
    import time

    from app.models.event import SdkEvent
    from app.models.log_analysis import LogReparseJob
    from app.services import log_parse_job_service as service

    monkeypatch.setattr(service, "PARSE_EXECUTOR_FACTORY", ThreadPoolExecutor)
    monkeypatch.setattr(service, "PARSE_TIMEOUT_SECONDS", 0.01)
    job = LogReparseJob(
        id=91,
        package_name="com.example.app",
        range_start=RANGE_START,
        range_end=RANGE_END,
        snapshot_end=NOW,
        status="running",
        lease_owner="worker-1",
        lease_expires_at=NOW.replace(hour=2),
        consecutive_timeout_count=0,
    )
    event = SdkEvent(
        id=20,
        event_type="log",
        package_name="com.example.app",
        server_ts=NOW,
        payload={"extra": "H1|i=GC"},
    )

    def slow_decode(_event, _job_id):
        time.sleep(0.03)
        return [], [], 0

    monkeypatch.setattr(service, "build_h1_and_click_rows", slow_decode)
    result = asyncio.run(
        service.process_parse_job_batch(
            BatchDb(job, [event]),
            91,
            worker_id="worker-1",
            now=NOW,
        )
    )

    assert result.h1_count == 1
    assert result.failed_h1_count == 1
    assert job.consecutive_timeout_count == 1


def test_mark_failed_cleans_lease_and_redacts_error() -> None:
    from app.models.log_analysis import LogReparseJob
    from app.services.log_parse_job_service import mark_parse_job_failed

    job = LogReparseJob(
        id=91,
        package_name="com.example.app",
        range_start=RANGE_START,
        range_end=RANGE_END,
        snapshot_end=NOW,
        status="running",
        lease_owner="worker-1",
        lease_expires_at=NOW.replace(hour=2),
    )
    db = BatchDb(job)

    asyncio.run(
        mark_parse_job_failed(
            db,
            91,
            RuntimeError("TOKEN postgres://admin:secret@example/db"),
            now=NOW,
        )
    )

    assert job.status == "failed"
    assert job.finished_at == NOW
    assert job.lease_owner is None
    assert "TOKEN" not in job.error_summary
    assert "postgres://" not in job.error_summary


def test_failure_rate_uses_h1_count_and_does_not_count_no_h1_events(monkeypatch) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from app.models.event import SdkEvent
    from app.models.log_analysis import LogReparseJob
    from app.services import log_parse_job_service as service

    monkeypatch.setattr(service, "PARSE_EXECUTOR_FACTORY", ThreadPoolExecutor)

    job = LogReparseJob(
        id=91,
        package_name="com.example.app",
        range_start=RANGE_START,
        range_end=RANGE_END,
        snapshot_end=NOW,
        status="running",
        lease_owner="worker-1",
        lease_expires_at=NOW.replace(hour=2),
    )
    events = [
        SdkEvent(id=index, event_type="log", package_name="com.example.app", server_ts=NOW, payload={"extra": "H1|i=GC"})
        for index in range(100)
    ]

    def mixed_rows(event, job_id):
        if event.id != 0:
            return [], [], 1
        return [
            {
                "job_id": job_id,
                "event_id": event.id,
                "event_server_ts": event.server_ts,
                "record_index": 1,
                "package_name": event.package_name,
                "status": "failed",
                "decoder_version": "2.0.0",
                "parsed_at": NOW,
            }
        ], [], 0

    monkeypatch.setattr(service, "build_h1_and_click_rows", mixed_rows)

    result = asyncio.run(
        service.process_parse_job_batch(
            BatchDb(job, events),
            91,
            worker_id="worker-1",
            now=NOW,
            batch_size=200,
        )
    )

    assert result.scanned == 100
    assert job.h1_count == 1
    assert job.failed_h1_count == 1


def test_failure_rate_counts_each_h1_row_in_a_multi_h1_event(monkeypatch) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from app.models.event import SdkEvent
    from app.models.log_analysis import LogReparseJob
    from app.services import log_parse_job_service as service

    monkeypatch.setattr(service, "PARSE_EXECUTOR_FACTORY", ThreadPoolExecutor)
    job = LogReparseJob(
        id=91,
        package_name="com.example.app",
        range_start=RANGE_START,
        range_end=RANGE_END,
        snapshot_end=NOW,
        status="running",
        lease_owner="worker-1",
        lease_expires_at=NOW.replace(hour=2),
    )
    events = [
        SdkEvent(
            id=index,
            event_type="log",
            package_name="com.example.app",
            server_ts=NOW,
            payload={"extra": "H1|i=GC"},
        )
        for index in range(50)
    ]

    def two_h1_rows(event, job_id):
        rows = []
        for record_index in (1, 2):
            rows.append(
                {
                    "job_id": job_id,
                    "event_id": event.id,
                    "event_server_ts": event.server_ts,
                    "record_index": record_index,
                    "package_name": event.package_name,
                    "status": "failed" if event.id < 21 and record_index == 1 else "success",
                    "decoder_version": "2.0.0",
                    "parsed_at": NOW,
                }
            )
        return rows, [], 0

    monkeypatch.setattr(service, "build_h1_and_click_rows", two_h1_rows)

    with pytest.raises(service.ParseJobFailure, match="20%"):
        asyncio.run(
            service.process_parse_job_batch(
                BatchDb(job, events),
                91,
                worker_id="worker-1",
                now=NOW,
                batch_size=200,
            )
        )

    assert job.h1_count == 100
    assert job.failed_h1_count == 21


def test_batch_preserves_successful_h1_and_failed_h1_subset_counts(monkeypatch) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from app.models.event import SdkEvent
    from app.models.log_analysis import LogReparseJob
    from app.services import log_parse_job_service as service

    monkeypatch.setattr(service, "PARSE_EXECUTOR_FACTORY", ThreadPoolExecutor)
    job = LogReparseJob(
        id=91,
        package_name="com.example.app",
        range_start=RANGE_START,
        range_end=RANGE_END,
        snapshot_end=NOW,
        status="running",
        lease_owner="worker-1",
        lease_expires_at=NOW.replace(hour=2),
    )
    events = [SdkEvent(id=1, event_type="log", package_name="com.example.app", server_ts=NOW, payload={"extra": "H1|i=GC|p=1||H1|i=GD|p=1"})]
    original = service.parse_host_final_result_line
    calls = 0

    def fail_first_h1(record):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("bad H1")
        return original(record)

    monkeypatch.setattr(service, "parse_host_final_result_line", fail_first_h1)
    db = BatchDb(job, events)
    result = asyncio.run(service.process_parse_job_batch(db, 91, worker_id="worker-1", now=NOW, batch_size=200))

    assert result.h1_count == 2
    assert result.failed_h1_count == 1
    assert job.h1_count == 2
    assert job.failed_h1_count == 1
    asyncio.run(service.publish_parse_job(db, job, now=NOW))
    assert job.status == "success"
    assert any("sdk_log_h1_declarations" in str(statement) for statement in db.statements)


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
