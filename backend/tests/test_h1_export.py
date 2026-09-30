from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace


def _event(extra):
    return SimpleNamespace(
        id=7,
        package_name="com.example.app",
        device_id="device-1",
        sdk_version="1.0.3",
        payload={"level": "info", "extra": extra, "device_model": "Pixel", "os": "14", "ver": "2.0"},
        client_ts=None,
        server_ts=datetime(2026, 9, 29, 8, tzinfo=timezone.utc),
    )


def test_h1_request_mode_defaults_and_rejects_unknown_value():
    from pydantic import ValidationError

    from app.schemas.log_export_schemas import LogExportCreateRequest

    assert LogExportCreateRequest(package_names=["com.example.app"]).export_mode == "raw"
    assert LogExportCreateRequest(package_names=["com.example.app"], export_mode="h1").export_mode == "h1"
    try:
        LogExportCreateRequest(package_names=["com.example.app"], export_mode="other")
    except ValidationError:
        pass
    else:
        raise AssertionError("unknown export mode must be rejected")


def test_h1_export_expands_every_record_and_keeps_raw_when_no_h1():
    from app.services.log_export_service import export_rows_for_event

    rows = export_rows_for_event(
        _event("H1|i=GC|p=1||H1|i=GD|p=2||H1|i=GE|p=3"),
        export_mode="h1",
    )
    assert [row.record_type for row in rows] == ["h1", "h1", "h1"]
    assert [row.record_index for row in rows] == [1, 2, 3]
    assert [row.content for row in rows] == ["H1|i=GC|p=1", "H1|i=GD|p=2", "H1|i=GE|p=3"]
    assert rows[0].device_model == "Pixel"

    raw_rows = export_rows_for_event(_event("=SUM(A1:A2),\"quoted\"\nnext"), export_mode="h1")
    assert len(raw_rows) == 1
    assert raw_rows[0].record_type == "raw"
    assert raw_rows[0].record_index is None
    assert raw_rows[0].content.startswith("=SUM")


def test_h1_csv_row_has_fixed_columns_and_formula_safe_content():
    import csv
    import io

    from app.services.log_export_service import H1_CSV_HEADER, csv_row_for_export, export_rows_for_event

    row = export_rows_for_event(_event("@danger"), export_mode="h1")[0]
    values = csv_row_for_export(row)
    assert H1_CSV_HEADER == [
        "event_id", "server_time", "package_name", "device_id", "device_model", "os", "ver",
        "sdk_version", "level", "record_type", "record_index", "content",
    ]
    assert len(values) == len(H1_CSV_HEADER)
    assert values[-1] == "'@danger"

    raw = export_rows_for_event(_event('=SUM(A1:A2),"quoted"\nnext'), export_mode="h1")[0]
    output = io.StringIO()
    csv.writer(output).writerow(csv_row_for_export(raw))
    parsed = next(csv.reader(io.StringIO(output.getvalue())))
    assert parsed[-1] == "'=SUM(A1:A2),\"quoted\"\nnext"
