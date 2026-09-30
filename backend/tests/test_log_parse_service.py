from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy.sql import Delete, Insert, Select
from sqlalchemy.dialects import postgresql

from app.models.event import SdkEvent
from app.models.log_analysis import LogDecode


EVENT_TS = datetime(2026, 8, 17, 1, 2, 3, tzinfo=timezone.utc)


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return self.rows


class FakeDb:
    def __init__(self, pending_rows=(), *, fail_success_insert=False):
        self.pending_rows = list(pending_rows)
        self.statements = []
        self.deleted = []
        self.inserted = []
        self.fail_success_insert = fail_success_insert
        self.failed_success_insert = False
        self.savepoint_commits = 0
        self.savepoint_rollbacks = 0

    class _Nested:
        def __init__(self, db):
            self.db = db

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            if exc_type is None:
                self.db.savepoint_commits += 1
            else:
                self.db.savepoint_rollbacks += 1
            return False

    def begin_nested(self):
        return self._Nested(self)

    async def execute(self, statement, *args, **kwargs):
        self.statements.append(statement)
        if isinstance(statement, Select):
            compiled = statement.compile(dialect=postgresql.dialect())
            limit = statement._limit_clause.value if statement._limit_clause is not None else None
            assert "FOR UPDATE" in str(compiled)
            assert "SKIP LOCKED" in str(compiled)
            rows = self.pending_rows[:limit] if limit is not None else self.pending_rows
            return Result(rows)
        if isinstance(statement, Delete):
            self.deleted.append(statement)
            return Result()
        if isinstance(statement, Insert):
            if self.fail_success_insert and not self.failed_success_insert:
                params = compiled_params(statement)
                if "success" in params.values():
                    self.failed_success_insert = True
                    raise RuntimeError("simulated structured insert failure")
            self.inserted.append(statement)
            return Result()
        raise AssertionError(f"unexpected statement: {statement}")


def pending_pair(*, extra: str = "H1|i=GC", event_id: int = 1001):
    event = SdkEvent(
        id=event_id,
        event_type="log",
        package_name="com.example.app",
        device_id="device-1",
        payload={"extra": extra},
        server_ts=EVENT_TS,
    )
    decode = LogDecode(
        event_id=event.id,
        event_server_ts=EVENT_TS,
        record_index=-1,
        package_name=event.package_name,
        device_id=event.device_id,
        status="pending",
        decoder_version="1.0.0",
    )
    return decode, event


def compiled_params(statement):
    return statement.compile(dialect=postgresql.dialect()).params


def params_for_row(statement, index: int):
    params = compiled_params(statement)
    suffix = f"_m{index}"
    return {
        key.removesuffix(suffix): value
        for key, value in params.items()
        if key.endswith(suffix)
    }


def test_pending_query_uses_skip_locked_and_caps_batch_size():
    from app.services import log_parse_service

    db = FakeDb([pending_pair(), pending_pair(), pending_pair()])
    result = asyncio.run(log_parse_service.process_pending_batch(db, batch_size=500))

    assert result.scanned == 3
    select_stmt = next(statement for statement in db.statements if isinstance(statement, Select))
    compiled = str(select_stmt.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in compiled
    assert "SKIP LOCKED" in compiled
    assert select_stmt._limit_clause.value == 50


def test_success_deletes_pending_and_inserts_stable_projected_records(monkeypatch):
    from app.services import log_parse_service

    decoded = [
        {
            "timestamp": "2026-08-17T01:02:03.000Z",
            "url": "https://one.example",
            "config_id": 1004,
            "window": "normal",
            "expected_click_count": 2,
            "actual_click_count": 1,
            "ad_click_count": 1,
            "interstitial_presentation_count": 3,
            "interstitial_click_count": 2,
            "interstitial_close_count": 1,
            "duration_ms": 58576,
            "final_reason": "planned-click-count-exhausted",
            "is_success": True,
        },
        {"url": "https://two.example", "config_id": 1005, "is_success": False},
    ]
    monkeypatch.setattr(log_parse_service, "decode_extra", lambda _extra: decoded)
    db = FakeDb([pending_pair()])

    result = asyncio.run(log_parse_service.process_pending_batch(db))

    assert result.success == 1
    assert result.unsupported == 0
    assert result.failed == 0
    assert len(db.deleted) == 1
    insert = db.inserted[-1]
    first = params_for_row(insert, 0)
    second = params_for_row(insert, 1)
    assert first["record_index"] == 0
    assert second["record_index"] == 1
    assert first["status"] == "success"
    assert second["status"] == "success"
    assert first["decoded_payload"] == decoded[0]
    assert first["expected_click_count"] == 2
    assert first["duration_ms"] == 58576
    assert first["is_success"] is True


def test_real_decoder_projects_click_ad_and_success_metrics():
    from app.services import log_parse_service

    extra = "H1|t=268H0A000|w=main|i=GC|p=2|pa=b11hfn1|a=b|s=b|r=p|u=FEm"
    db = FakeDb([pending_pair(extra=extra)])

    result = asyncio.run(log_parse_service.process_pending_batch(db))

    assert result.success == 1
    row = params_for_row(db.inserted[-1], 0)
    assert row["actual_click_count"] == 1
    assert row["ad_click_count"] == 1
    assert row["is_success"] is True


def test_unsupported_replaces_pending_with_record_zero(monkeypatch):
    from app.services import log_parse_service

    monkeypatch.setattr(log_parse_service, "decode_extra", lambda _extra: [])
    db = FakeDb([pending_pair(extra="unknown-format")])

    result = asyncio.run(log_parse_service.process_pending_batch(db))

    assert result.success == 0
    assert result.unsupported == 1
    assert result.failed == 0
    row = params_for_row(db.inserted[-1], 0)
    assert row["record_index"] == 0
    assert row["status"] == "unsupported"
    assert row["decoded_payload"] == {}


def test_failed_parse_is_redacted_and_limited(monkeypatch):
    from app.services import log_parse_service

    secret = "EXTRA_SECRET_TOKEN postgres://admin:password@example.test/db"

    def raise_error(_extra):
        raise RuntimeError(secret + "\nTraceback (most recent call last):")

    monkeypatch.setattr(log_parse_service, "decode_extra", raise_error)
    db = FakeDb([pending_pair(extra=secret)])

    result = asyncio.run(log_parse_service.process_pending_batch(db))

    assert result.failed == 1
    assert result.success == 0
    row = params_for_row(db.inserted[-1], 0)
    assert row["record_index"] == 0
    assert row["status"] == "failed"
    assert len(row["parse_error"]) <= 512
    assert "RuntimeError" in row["parse_error"]
    assert secret not in row["parse_error"]
    assert "postgres://" not in row["parse_error"]
    assert "Traceback" not in row["parse_error"]


def test_decode_timeout_becomes_failed_without_stopping_batch(monkeypatch):
    from app.services import log_parse_service

    monkeypatch.setattr(log_parse_service, "PARSE_TIMEOUT_SECONDS", 0.001)

    def slow_decode(_extra):
        import time

        time.sleep(0.05)
        return []

    monkeypatch.setattr(log_parse_service, "decode_extra", slow_decode)
    db = FakeDb([pending_pair()])

    result = asyncio.run(log_parse_service.process_pending_batch(db))

    assert result.failed == 1
    row = params_for_row(db.inserted[-1], 0)
    assert row["status"] == "failed"
    assert "TimeoutError" in row["parse_error"]


def test_structured_insert_failure_isolated_and_next_pending_is_processed(monkeypatch):
    from app.services import log_parse_service

    decoded = [{"config_id": 1004, "window": "main", "final_reason": "planned-click-count-exhausted"}]
    monkeypatch.setattr(log_parse_service, "decode_extra", lambda _extra: decoded)
    db = FakeDb(
        [pending_pair(event_id=1001), pending_pair(event_id=1002)],
        fail_success_insert=True,
    )

    result = asyncio.run(log_parse_service.process_pending_batch(db))

    assert result.scanned == 2
    assert result.failed == 1
    assert result.success == 1
    assert db.failed_success_insert is True
    assert db.savepoint_rollbacks >= 1
    statuses = [
        params_for_row(statement, 0)["status"]
        for statement in db.inserted
    ]
    assert statuses == ["failed", "success"]


def test_admin_lifespan_starts_and_cancels_only_etl_task(monkeypatch):
    from types import SimpleNamespace

    from app import admin_main

    started = {"etl": False}
    cancelled = {"etl": False}

    async def blocking_loop(name):
        started[name] = True
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled[name] = True
            raise

    async def fake_etl():
        await blocking_loop("etl")

    monkeypatch.setattr(
        admin_main,
        "get_settings",
        lambda: SimpleNamespace(
            ADMIN_TOKEN="a" * 40,
            CDN_BASE_URL="https://cdn.test.local",
            COS_BUCKET="sdk-config-bucket",
        ),
    )
    monkeypatch.setattr(admin_main, "etl_refresh_loop", fake_etl)

    async def run_lifespan():
        async with admin_main.lifespan(admin_main.app):
            await asyncio.sleep(0)

    asyncio.run(run_lifespan())

    assert started == {"etl": True}
    assert cancelled == {"etl": True}


def test_admin_lifespan_cleans_up_etl_task_when_body_raises(monkeypatch):
    from types import SimpleNamespace

    from app import admin_main

    started = {"etl": False}
    cancelled = {"etl": False}

    async def blocking_loop(name):
        started[name] = True
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled[name] = True
            raise

    async def fake_etl():
        await blocking_loop("etl")

    monkeypatch.setattr(
        admin_main,
        "get_settings",
        lambda: SimpleNamespace(
            ADMIN_TOKEN="a" * 40,
            CDN_BASE_URL="https://cdn.test.local",
            COS_BUCKET="sdk-config-bucket",
        ),
    )
    monkeypatch.setattr(admin_main, "etl_refresh_loop", fake_etl)

    async def run_lifespan():
        async with admin_main.lifespan(admin_main.app):
            await asyncio.sleep(0)
            raise RuntimeError("body failed")

    with pytest.raises(RuntimeError, match="body failed"):
        asyncio.run(run_lifespan())

    assert started == {"etl": True}
    assert cancelled == {"etl": True}
