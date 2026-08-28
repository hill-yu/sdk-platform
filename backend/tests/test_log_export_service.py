from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

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
