from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import date, datetime, timezone

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


class ScalarResult:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.statements = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, statement, *args, **kwargs):
        self.statements.append(statement)
        if isinstance(statement, Select):
            return ScalarResult(self.rows)
        if isinstance(statement, (Delete, Insert)):
            return ScalarResult()
        raise AssertionError(f"unexpected statement: {statement}")

    async def commit(self):
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
    assert any(value == "2.0.0" for value in params.values())
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
