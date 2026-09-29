from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.services import usage_duration_service


def test_resolve_range_defaults_to_utc_plus_8_today(monkeypatch):
    monkeypatch.setattr(usage_duration_service, "business_today", lambda: date(2026, 9, 29))
    start, end = usage_duration_service.resolve_usage_date_range(None, None)
    assert start == datetime(2026, 9, 28, 16, tzinfo=timezone.utc)
    assert end == datetime(2026, 9, 29, 16, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("date_from", "date_to", "message"),
    [
        (date(2026, 9, 1), None, "必须成对提供"),
        (None, date(2026, 9, 1), "必须成对提供"),
        (date(2026, 9, 2), date(2026, 9, 1), "结束日期不能早于开始日期"),
        (date(2026, 8, 1), date(2026, 9, 1), "最多查询 31 天"),
    ],
)
def test_resolve_range_rejects_invalid_ranges(date_from, date_to, message):
    with pytest.raises(ValueError, match=message):
        usage_duration_service.resolve_usage_date_range(date_from, date_to)


def test_build_filters_uses_all_exact_match_fields():
    filters = usage_duration_service.build_usage_filters(
        package_name="com.example.app",
        device_id="device-1",
        sdk_version="1.0.3",
        ver="1.0",
        range_start=datetime(2026, 9, 1, tzinfo=timezone.utc),
        range_end=datetime(2026, 9, 2, tzinfo=timezone.utc),
    )
    sql = " AND ".join(
        str(item.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        for item in filters
    )
    assert "package_name = 'com.example.app'" in sql
    assert "device_id = 'device-1'" in sql
    assert "sdk_version = '1.0.3'" in sql
    assert "app_version = '1.0'" in sql
    assert "server_ts >= " in sql
    assert "server_ts < " in sql


class Result:
    def __init__(self, *, mapping=None, rows=None):
        self.mapping = mapping
        self.rows = rows or []

    def mappings(self):
        return self

    def one(self):
        return self.mapping

    def scalars(self):
        return self

    def all(self):
        return self.rows


class Session:
    def __init__(self, event):
        self.results = [
            Result(mapping={"total_duration_s": 120, "report_count": 2, "device_count": 1}),
            Result(rows=[event]),
        ]
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self.results.pop(0)


@pytest.mark.asyncio
async def test_query_returns_summary_pagination_and_utc_plus_8_items():
    event = SimpleNamespace(
        id=7,
        package_name="com.example.app",
        device_id="device-1",
        device_model="iPhone13,2",
        os="17.5.1",
        app_version="1.0",
        sdk_version="1.0.3",
        duration_s=60,
        server_ts=datetime(2026, 9, 29, 8, 30, tzinfo=timezone.utc),
        ip="203.0.113.10",
        user_agent="ExampleSDK/1.0.3",
    )
    db = Session(event)
    data = await usage_duration_service.get_usage_durations(
        db,
        package_name="com.example.app",
        device_id=None,
        sdk_version=None,
        ver=None,
        date_from=date(2026, 9, 29),
        date_to=date(2026, 9, 29),
        page=1,
        page_size=20,
    )
    assert data["summary"] == {
        "total_duration_s": 120,
        "report_count": 2,
        "device_count": 1,
    }
    assert data["total"] == 2
    assert data["items"][0]["ver"] == "1.0"
    assert data["items"][0]["server_time"] == "2026-09-29T16:30:00+08:00"
    assert len(db.statements) == 2
