from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import Delete, Insert, Select

from app.models.event import SdkEvent


EVENT_TS = datetime(2026, 8, 17, 1, 2, 3, tzinfo=timezone.utc)
H1_EXTRA = "H1|t=268H0A000|w=main|i=GC|p=2|pa=b11hfn1|a=b|s=b|r=p|u=FEm"


def event(*, event_id: int = 1001, server_ts: datetime = EVENT_TS, extra: object = H1_EXTRA):
    return SdkEvent(
        id=event_id,
        event_type="log",
        package_name="com.example.app",
        device_id="device-1",
        payload={"extra": extra},
        server_ts=server_ts,
    )


def payload_hash(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def params_for_row(statement, index: int):
    params = statement.compile(dialect=postgresql.dialect()).params
    suffix = f"_m{index}"
    return {
        key.removesuffix(suffix): value
        for key, value in params.items()
        if key.endswith(suffix)
    }


class ScalarResult:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, rows=(), *, fail_commit=False):
        self.rows = list(rows)
        self.statements = []
        self.commits = 0
        self.rollbacks = 0
        self.fail_commit = fail_commit

    async def execute(self, statement, *args, **kwargs):
        self.statements.append(statement)
        if isinstance(statement, Select):
            return ScalarResult(self.rows)
        if isinstance(statement, (Delete, Insert)):
            return ScalarResult()
        raise AssertionError(f"unexpected statement: {statement}")

    async def commit(self):
        if self.fail_commit:
            raise RuntimeError("commit failed")
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    class _Nested:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def begin_nested(self):
        return self._Nested()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_backfill_query_is_bounded_to_string_log_events_and_stable_cursor():
    from scripts.backfill_log_decodes import (
        BackfillFilters,
        build_event_query,
    )

    statement = build_event_query(
        BackfillFilters(
            date_from=date(2026, 8, 17),
            date_to=date(2026, 8, 18),
            package_name="com.example.app",
            status="failed",
            decoder_version_before="2.0.0",
        ),
        cursor_ts=EVENT_TS,
        cursor_id=1001,
        batch_size=25,
    )
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    params = statement.compile(dialect=postgresql.dialect()).params

    assert "sdk_events.event_type = %(event_type_1)s" in compiled
    assert "jsonb_typeof(sdk_events.payload -> 'extra') = 'string'" in compiled
    assert "sdk_events.server_ts >" in compiled
    assert "sdk_events.server_ts =" in compiled
    assert "sdk_events.id >" in compiled
    assert "ORDER BY sdk_events.server_ts, sdk_events.id" in compiled
    assert statement._limit_clause.value == 25
    assert any(value == "log" for value in params.values())
    assert any(value == "failed" for value in params.values())
    assert all(value in params.values() for value in (2, 0, 0))
    assert datetime(2026, 8, 16, 16, tzinfo=timezone.utc) in params.values()
    assert datetime(2026, 8, 17, 16, tzinfo=timezone.utc) in params.values()


def test_backfill_rejects_unbounded_requests_and_requires_date_pair():
    from scripts.backfill_log_decodes import (
        BackfillFilters,
        validate_apply_confirmation,
        validate_filters,
    )

    with pytest.raises(ValueError, match="范围"):
        validate_filters(BackfillFilters())
    with pytest.raises(ValueError, match="date-from.*date-to"):
        validate_filters(BackfillFilters(date_from=date(2026, 8, 17)))
    with pytest.raises(ValueError, match="confirm"):
        validate_apply_confirmation(True, None)
    validate_apply_confirmation(False, None)


def test_decoder_version_filter_uses_numeric_semver_and_rejects_invalid_values():
    from scripts.backfill_log_decodes import (
        BackfillFilters,
        build_event_query,
        parse_decoder_version,
        validate_filters,
    )

    assert parse_decoder_version("1.8.9") == (1, 8, 9)
    assert parse_decoder_version("1.8.9") < parse_decoder_version("1.9.0")
    assert not parse_decoder_version("1.10.0") < parse_decoder_version("1.9.0")
    assert not parse_decoder_version("2.0.0") < parse_decoder_version("1.9.0")
    with pytest.raises(ValueError, match="x.y.z"):
        validate_filters(
            BackfillFilters(
                package_name="com.example.app",
                decoder_version_before="1.9",
            )
        )

    statement = build_event_query(
        BackfillFilters(
            package_name="com.example.app",
            decoder_version_before="1.9.0",
        )
    )
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    params = statement.compile(dialect=postgresql.dialect()).params
    assert "split_part" in compiled
    assert "CAST" in compiled
    assert "sdk_log_decodes.decoder_version <" not in compiled
    assert all(value in params.values() for value in (1, 9, 0))


def test_invalid_decoder_version_is_rejected_before_engine_creation(monkeypatch):
    import scripts.backfill_log_decodes as backfill

    args = SimpleNamespace(
        date_from=None,
        date_to=None,
        package_name="com.example.app",
        status=None,
        decoder_version_before="1.9",
        cursor_ts=None,
        cursor_id=None,
        batch_size=10,
        apply=False,
        confirm=None,
    )
    monkeypatch.setattr(backfill, "_build_parser", lambda: SimpleNamespace(parse_args=lambda: args))
    monkeypatch.setattr(
        backfill,
        "create_async_engine",
        lambda *_args, **_kwargs: pytest.fail("engine must not be created"),
    )

    with pytest.raises(SystemExit) as error:
        backfill.main()
    assert error.value.code == 1


def test_cli_engine_and_dispose_share_one_event_loop(monkeypatch):
    import scripts.backfill_log_decodes as backfill

    loops = []

    class FakeEngine:
        def __init__(self):
            self.loop = asyncio.get_running_loop()
            self.disposed = False

        async def dispose(self):
            loops.append((self.loop, asyncio.get_running_loop(), "dispose"))
            self.disposed = True

    engine = FakeEngine.__new__(FakeEngine)

    def fake_create_engine(_url):
        FakeEngine.__init__(engine)
        loops.append((engine.loop, asyncio.get_running_loop(), "create"))
        return engine

    def fake_sessionmaker(received_engine, **_kwargs):
        assert received_engine is engine
        assert asyncio.get_running_loop() is engine.loop
        return object()

    async def fake_run(*_args, **_kwargs):
        assert asyncio.get_running_loop() is engine.loop
        raise RuntimeError(f"{H1_EXTRA} postgres://admin:secret@example/db Traceback")

    monkeypatch.setattr(backfill, "create_async_engine", fake_create_engine)
    monkeypatch.setattr(backfill, "async_sessionmaker", fake_sessionmaker)
    monkeypatch.setattr(backfill, "run_backfill", fake_run)

    with pytest.raises(RuntimeError, match="H1"):
        asyncio.run(
            backfill._run_cli(
                database_url="postgresql+asyncpg://admin:secret@example/db",
                filters=backfill.BackfillFilters(package_name="com.example.app"),
                apply=False,
                batch_size=10,
                cursor_ts=None,
                cursor_id=None,
                emit=lambda _line: None,
            )
        )

    assert loops[0][0] is loops[0][1]
    assert loops[1][0] is loops[1][1]
    assert engine.disposed is True


def test_cli_failure_is_sanitized_and_engine_is_disposed(monkeypatch, capsys):
    import scripts.backfill_log_decodes as backfill

    args = SimpleNamespace(
        date_from=None,
        date_to=None,
        package_name="com.example.app",
        status=None,
        decoder_version_before=None,
        cursor_ts=None,
        cursor_id=None,
        batch_size=10,
        apply=False,
        confirm=None,
    )
    disposed = {"value": False}

    class FakeEngine:
        async def dispose(self):
            disposed["value"] = True

    async def fake_run_backfill(*_args, **_kwargs):
        raise RuntimeError(f"{H1_EXTRA} postgres://admin:secret@example/db Traceback")

    monkeypatch.setattr(backfill, "_build_parser", lambda: SimpleNamespace(parse_args=lambda: args))
    monkeypatch.setattr(backfill, "create_async_engine", lambda *_args, **_kwargs: FakeEngine())
    monkeypatch.setattr(backfill, "async_sessionmaker", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(backfill, "run_backfill", fake_run_backfill)

    with pytest.raises(SystemExit) as error:
        backfill.main()

    assert error.value.code == 1
    output = capsys.readouterr().err
    assert "RuntimeError" in output
    assert "backfill failed" in output
    assert H1_EXTRA not in output
    assert "postgres://" not in output
    assert "Traceback" not in output
    assert disposed["value"] is True


def test_dry_run_reads_only_and_preserves_original_payload_hash():
    from scripts.backfill_log_decodes import BackfillFilters, process_backfill_batch

    row = event()
    before = payload_hash(row.payload)
    session = FakeSession([row])

    result = asyncio.run(
        process_backfill_batch(
            session,
            BackfillFilters(package_name="com.example.app"),
            apply=False,
            batch_size=10,
        )
    )

    assert result.scanned == 1
    assert result.success == 1
    assert result.last_event_id == row.id
    assert result.last_event_server_ts == row.server_ts
    assert not any(isinstance(statement, (Insert, Delete)) for statement in session.statements)
    assert payload_hash(row.payload) == before
    assert "extra" not in result.report_line


def test_apply_uses_upsert_and_removes_old_record_indexes_without_mutating_event():
    from scripts.backfill_log_decodes import BackfillFilters, process_backfill_batch

    row = event()
    before = payload_hash(row.payload)
    session = FakeSession([row])

    result = asyncio.run(
        process_backfill_batch(
            session,
            BackfillFilters(package_name="com.example.app"),
            apply=True,
            batch_size=10,
        )
    )

    assert result.success == 1
    delete_stmt = next(statement for statement in session.statements if isinstance(statement, Delete))
    insert_stmt = next(statement for statement in session.statements if isinstance(statement, Insert))
    assert "sdk_log_decodes.event_id" in str(delete_stmt.compile(dialect=postgresql.dialect()))
    compiled = str(insert_stmt.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (event_id, event_server_ts, record_index) DO UPDATE" in compiled
    assert payload_hash(row.payload) == before


def test_real_decoder_backfill_projection_matches_online_metrics():
    from scripts.backfill_log_decodes import BackfillFilters, process_backfill_batch

    row = event(extra=H1_EXTRA)
    session = FakeSession([row])

    result = asyncio.run(
        process_backfill_batch(
            session,
            BackfillFilters(package_name="com.example.app"),
            apply=True,
            batch_size=10,
        )
    )

    assert result.success == 1
    insert_stmt = next(statement for statement in session.statements if isinstance(statement, Insert))
    params = insert_stmt.compile(dialect=postgresql.dialect()).params
    assert 1 in params.values()
    assert True in params.values()


def test_backfill_report_contains_counts_and_cursor_but_not_raw_extra():
    from scripts.backfill_log_decodes import BackfillBatchResult

    result = BackfillBatchResult(
        scanned=2,
        success=1,
        unsupported=1,
        failed=0,
        last_event_id=1002,
        last_event_server_ts=EVENT_TS,
    )
    assert "scanned=2" in result.report_line
    assert "success=1" in result.report_line
    assert "last_cursor=" in result.report_line
    assert H1_EXTRA not in result.report_line


def test_run_backfill_commits_each_apply_batch_and_preserves_final_cursor():
    from scripts.backfill_log_decodes import BackfillFilters, run_backfill

    first_session = FakeSession([event()])
    final_session = FakeSession([])
    sessions = [first_session, final_session]

    def session_factory():
        return sessions.pop(0)

    reports = []
    result = asyncio.run(
        run_backfill(
            session_factory,
            BackfillFilters(package_name="com.example.app"),
            apply=True,
            batch_size=1,
            emit=reports.append,
        )
    )

    assert result.scanned == 1
    assert result.last_event_id == 1001
    assert first_session.commits == 1
    assert final_session.commits == 1
    assert "scanned=1" in reports[0]
    assert "cumulative_scanned=1" in reports[-1]


def test_failed_batch_rolls_back_only_that_batch_and_keeps_prior_report_cursor():
    from scripts.backfill_log_decodes import BackfillFilters, run_backfill

    first_session = FakeSession([event(event_id=1001)])
    failed_session = FakeSession([event(event_id=1002)], fail_commit=True)
    sessions = [first_session, failed_session]

    def session_factory():
        return sessions.pop(0)

    reports = []
    with pytest.raises(RuntimeError, match="commit failed"):
        asyncio.run(
            run_backfill(
                session_factory,
                BackfillFilters(package_name="com.example.app"),
                apply=True,
                batch_size=1,
                emit=reports.append,
            )
        )

    assert first_session.commits == 1
    assert first_session.rollbacks == 0
    assert failed_session.commits == 0
    assert failed_session.rollbacks == 1
    assert len(reports) == 1
    assert "1001" in reports[0]
    assert "1002" not in reports[0]


class StatefulSession(FakeSession):
    def __init__(self, rows, state):
        super().__init__(rows)
        self.state = state

    async def execute(self, statement, *args, **kwargs):
        self.statements.append(statement)
        if isinstance(statement, Select):
            return ScalarResult(self.rows)
        if isinstance(statement, Delete):
            self.state.clear()
            return ScalarResult()
        if isinstance(statement, Insert):
            row = params_for_row(statement, 0)
            self.state.add((row["event_id"], row["event_server_ts"], row["record_index"]))
            return ScalarResult()
        raise AssertionError(f"unexpected statement: {statement}")


def test_repeated_apply_is_idempotent_and_removes_stale_record_indexes():
    from scripts.backfill_log_decodes import BackfillFilters, process_backfill_batch

    row = event()
    state = {
        (row.id, row.server_ts, -1),
        (row.id, row.server_ts, 0),
        (row.id, row.server_ts, 3),
    }
    before = payload_hash(row.payload)

    first_session = StatefulSession([row], state)
    asyncio.run(
        process_backfill_batch(
            first_session,
            BackfillFilters(package_name="com.example.app"),
            apply=True,
            batch_size=10,
        )
    )
    first_state = set(state)

    second_session = StatefulSession([row], state)
    asyncio.run(
        process_backfill_batch(
            second_session,
            BackfillFilters(package_name="com.example.app"),
            apply=True,
            batch_size=10,
        )
    )

    assert first_state == {(row.id, row.server_ts, 0)}
    assert state == first_state
    assert len(state) == len(first_state)
    assert payload_hash(row.payload) == before
    for statement in first_session.statements + second_session.statements:
        if isinstance(statement, (Delete, Insert)):
            compiled = str(statement.compile(dialect=postgresql.dialect()))
            assert "sdk_log_decodes" in compiled
            assert "sdk_events" not in compiled
