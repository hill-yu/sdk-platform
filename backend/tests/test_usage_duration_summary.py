from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql


START = datetime(2026, 9, 29, 0, tzinfo=timezone.utc)
END = datetime(2026, 9, 30, 0, tzinfo=timezone.utc)


class Result:
    def __init__(self, *, scalar=None, rows=()):
        self.scalar = scalar
        self.rows = list(rows)

    def scalar_one(self):
        return self.scalar

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def scalars(self):
        return self


class Db:
    def __init__(self, results):
        self.results = list(results)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self.results.pop(0)


def test_latest_device_query_uses_partitioned_window_and_stable_tiebreaker():
    from app.services.usage_duration_service import build_latest_usage_query

    statement = build_latest_usage_query(
        package_name="com.example.app",
        device_model=None,
        range_start=START,
        range_end=END,
    )
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "row_number() OVER (PARTITION BY sdk_usage_durations.package_name, sdk_usage_durations.device_id ORDER BY sdk_usage_durations.server_ts DESC, sdk_usage_durations.id DESC)" in sql
    assert "sdk_usage_durations.server_ts >=" in sql
    assert "sdk_usage_durations.server_ts <" in sql


def test_latest_query_does_not_filter_device_model_before_partitioning():
    from app.services.usage_duration_service import build_latest_usage_query

    statement = build_latest_usage_query(
        package_name="com.example.app",
        device_model="A",
        range_start=START,
        range_end=END,
    )
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "WHERE sdk_usage_durations.device_model" not in sql


def test_usage_devices_query_filters_model_after_latest_partition():
    from app.services.usage_duration_service import get_usage_devices

    db = Db([Result(scalar=0), Result(rows=[])])
    asyncio.run(
        get_usage_devices(
            db,
            package_name="com.example.app",
            device_model="A",
            range_start=START,
            range_end=END,
            page=1,
            page_size=20,
        )
    )
    sql = str(db.statements[1].compile(dialect=postgresql.dialect()))
    assert "latest_rank =" in sql
    assert "device_model" in sql
    assert sql.index("latest_rank") < sql.rindex("device_model")


def test_usage_summary_uses_only_latest_device_and_computes_four_buckets():
    from app.services.usage_duration_service import get_usage_summary

    db = Db(
        [
            Result(scalar=2),
            Result(rows=[SimpleNamespace(
                package_name="com.example.app",
                device_model="iPhone13,2",
                device_count=2,
                total_duration_s=540,
                average_duration_s=270,
                le_300_count=1,
                between_301_600_count=1,
                between_601_899_count=0,
                ge_900_count=0,
                last_report_at=datetime(2026, 9, 29, 8, tzinfo=timezone.utc),
            )]),
        ]
    )

    result = asyncio.run(
        get_usage_summary(
            db,
            package_name="com.example.app",
            range_start=START,
            range_end=END,
            page=1,
            page_size=20,
            sort_by="package_name",
            sort_order="asc",
        )
    )

    item = result["items"][0]
    assert item["total_duration_s"] == 540
    assert item["device_count"] == 2
    assert item["average_duration_s"] == 270
    assert [(bucket["key"], bucket["count"], bucket["share"]) for bucket in item["buckets"]] == [
        ("le_300", 1, 0.5),
        ("301_600", 1, 0.5),
        ("601_899", 0, 0.0),
        ("ge_900", 0, 0.0),
    ]


def test_usage_devices_returns_latest_rows_for_expanded_package_and_model():
    from app.services.usage_duration_service import get_usage_devices

    row = SimpleNamespace(
        package_name="com.example.app",
        device_id="device-1",
        device_model="Pixel",
        duration_s=900,
        sdk_version="1.0.3",
        app_version="2.0",
        server_ts=datetime(2026, 9, 29, 8, tzinfo=timezone.utc),
    )
    db = Db([Result(scalar=1), Result(rows=[row])])
    result = asyncio.run(
        get_usage_devices(
            db,
            package_name="com.example.app",
            device_model="Pixel",
            range_start=START,
            range_end=END,
            page=1,
            page_size=20,
        )
    )
    assert result["total"] == 1
    assert result["items"][0]["duration_s"] == 900
    assert result["items"][0]["app_version"] == "2.0"


def test_usage_summary_and_devices_have_stable_tie_breakers():
    from app.services.usage_duration_service import get_usage_devices, get_usage_summary

    summary_db = Db([Result(scalar=0), Result(rows=[])])
    asyncio.run(get_usage_summary(
        summary_db,
        package_name=None,
        range_start=START,
        range_end=END,
        page=1,
        page_size=20,
        sort_by="device_count",
        sort_order="desc",
    ))
    summary_sql = str(summary_db.statements[1].compile(dialect=postgresql.dialect()))
    assert "package_name" in summary_sql
    assert "device_model" in summary_sql

    devices_db = Db([Result(scalar=0), Result(rows=[])])
    asyncio.run(get_usage_devices(
        devices_db,
        package_name="com.example.app",
        device_model="A",
        range_start=START,
        range_end=END,
        page=1,
        page_size=20,
    ))
    devices_sql = str(devices_db.statements[1].compile(dialect=postgresql.dialect()))
    assert "server_ts DESC" in devices_sql
    assert "id DESC" in devices_sql
    assert "device_id ASC" in devices_sql
