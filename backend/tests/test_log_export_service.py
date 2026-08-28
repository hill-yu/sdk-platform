from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError


def test_log_export_job_model_has_required_columns():
    from app.models.log_export_job import LogExportJob

    columns = LogExportJob.__table__.columns
    assert set(columns.keys()) == {
        "id", "status", "package_names", "device_id", "log_level",
        "date_from", "date_to", "file_path", "row_count", "error_message",
        "created_at", "started_at", "finished_at",
    }
    assert columns["package_names"].nullable is False
    assert columns["file_path"].nullable is True


def test_log_export_migration_is_idempotent_and_indexed():
    sql = Path("scripts/migrate_log_export_jobs.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS sdk_log_export_jobs" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_log_export_jobs_status_created" in sql
    assert "CHECK (status IN ('pending', 'running', 'success', 'failed'))" in sql


def test_create_request_trims_and_deduplicates_packages():
    from app.schemas.log_export_schemas import LogExportCreateRequest

    body = LogExportCreateRequest(
        package_names=[" com.a ", "com.b", "com.a"], device_id=" ",
        date_from="2026-08-28", date_to="2026-08-28",
    )
    assert body.package_names == ["com.a", "com.b"]
    assert body.device_id is None


def test_create_request_rejects_invalid_filters():
    from app.schemas.log_export_schemas import LogExportCreateRequest

    with pytest.raises(ValidationError):
        LogExportCreateRequest(package_names=[])
    with pytest.raises(ValidationError):
        LogExportCreateRequest(package_names=["com.a"], date_from="2026-08-29", date_to="2026-08-28")


def test_csv_row_preserves_extra_and_converts_time_to_utc8():
    from app.services.log_export_service import csv_row_for_event

    event = type("Event", (), {
        "id": 7, "package_name": "com.a", "device_id": "d1", "sdk_version": "1.0.3",
        "payload": {"level": "info", "tag": "t", "message": "m", "extra": "{H1|a=1}"},
        "client_ts": None,
        "server_ts": datetime(2026, 8, 28, 1, 2, 3, tzinfo=timezone.utc),
    })()
    assert csv_row_for_event(event) == [
        "7", "com.a", "d1", "1.0.3", "info", "t", "m", "{H1|a=1}", "", "2026-08-28 09:02:03"
    ]


def test_csv_row_escapes_formula_prefix_and_serializes_legacy_extra():
    from app.services.log_export_service import csv_row_for_event

    event = type("Event", (), {
        "id": 8, "package_name": "com.a", "device_id": None, "sdk_version": None,
        "payload": {"level": "info", "message": "=cmd()", "extra": ["raw", 1]},
        "client_ts": None, "server_ts": datetime(2026, 8, 28, tzinfo=timezone.utc),
    })()
    row = csv_row_for_event(event)
    assert row[6] == "'=cmd()"
    assert row[7] == '["raw",1]'


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _ClaimSession:
    def __init__(self, job):
        self.job = job
        self.statement = None
        self.committed = False

    async def execute(self, statement):
        self.statement = statement
        return _ScalarResult(self.job)

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_claim_pending_job_uses_skip_locked_and_marks_running():
    from app.services.log_export_service import claim_next_job

    job = SimpleNamespace(status="pending", started_at=None)
    session = _ClaimSession(job)
    claimed = await claim_next_job(session)
    assert claimed is job
    assert job.status == "running"
    assert job.started_at is not None
    assert session.committed is True
    from sqlalchemy.dialects import postgresql
    compiled = str(session.statement.compile(dialect=postgresql.dialect())).upper()
    assert "SKIP LOCKED" in compiled


def test_apply_job_filters_uses_log_packages_and_selected_filters():
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql
    from app.models.event import SdkEvent
    from app.services.log_export_service import apply_job_filters

    job = SimpleNamespace(
        package_names=["com.a", "com.b"], device_id="d1", log_level="error",
        date_from=None, date_to=None,
    )
    sql = str(apply_job_filters(select(SdkEvent), job).compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True},
    ))
    assert "sdk_events.event_type = 'log'" in sql
    assert "sdk_events.package_name IN ('com.a', 'com.b')" in sql
    assert "sdk_events.device_id = 'd1'" in sql
    assert "error" in sql
