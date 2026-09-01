from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import pytest

from types import SimpleNamespace

from app.services import analysis_service
from app.services.analysis_service import get_breakdown, get_events, get_summary, get_trend
from sqlalchemy.dialects import postgresql


class _Rows:
    def mappings(self) -> "_Rows":
        return self

    def all(self) -> list[Any]:
        return []


class _CapturingSession:
    def __init__(self) -> None:
        self.statement: Any = None
        self.params: dict[str, Any] = {}

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _Rows:
        self.statement = statement
        self.params = params or {}
        return _Rows()


class _SummaryRows:
    def mappings(self) -> "_SummaryRows":
        return self

    def one(self) -> dict[str, int]:
        return {
            "today_pv": 0,
            "today_events": 0,
            "today_uv": 0,
            "yesterday_pv": 0,
            "yesterday_events": 0,
            "yesterday_uv": 0,
            "error_count": 0,
        }


class _SummarySession(_CapturingSession):
    async def execute(self, statement: Any, params: dict[str, Any]) -> _SummaryRows:
        self.statement = statement
        self.params = params
        return _SummaryRows()


@pytest.mark.asyncio
@pytest.mark.parametrize("range_value", ["24h", "7d"])
async def test_trend_sql_binds_the_complete_event_type_parameter(range_value: str) -> None:
    db = _CapturingSession()

    await get_trend(db, range_value=range_value, event_type=None)  # type: ignore[arg-type]

    assert "event_type" in db.statement._bindparams
    assert "event_typ" not in db.statement._bindparams
    assert ":event_type::varchar" not in str(db.statement)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("range_value", "expected_start_date"),
    [("7d", date(2026, 8, 11)), ("30d", date(2026, 7, 19))],
)
async def test_trend_binds_start_date_from_utc_plus_8_business_today(
    monkeypatch, range_value: str, expected_start_date: date
) -> None:
    db = _CapturingSession()
    monkeypatch.setattr(analysis_service, "business_today", lambda: date(2026, 8, 17))

    await get_trend(db, range_value=range_value)  # type: ignore[arg-type]

    assert db.params["start_date"] == expected_start_date


class _TrendRows:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def mappings(self) -> "_TrendRows":
        return self

    def all(self) -> list[dict[str, Any]]:
        return self.rows


class _TrendSession:
    async def execute(self, _statement: Any, _params: dict[str, Any]) -> _TrendRows:
        return _TrendRows(
            [
                {
                    "time": datetime(2026, 8, 17, 10, tzinfo=timezone.utc),
                    "count": 4,
                    "uv": 3,
                }
            ]
        )


@pytest.mark.asyncio
async def test_24_hour_trend_serializes_times_as_utc_plus_8_business_time() -> None:
    result = await get_trend(_TrendSession(), range_value="24h")  # type: ignore[arg-type]

    assert result["points"][0]["time"] == "2026-08-17T18:00:00+08:00"


@pytest.mark.asyncio
async def test_summary_binds_utc_boundaries_for_utc_plus_8_business_days(monkeypatch) -> None:
    db = _SummarySession()
    monkeypatch.setattr(analysis_service, "business_today", lambda: date(2026, 8, 17))

    await get_summary(db)  # type: ignore[arg-type]

    assert db.params["today"] == datetime(2026, 8, 16, 16, tzinfo=timezone.utc)
    assert db.params["yesterday"] == datetime(2026, 8, 15, 16, tzinfo=timezone.utc)


class _EventResults:
    def __init__(self, *, total: int | None = None, rows: list[Any] | None = None):
        self.total = total
        self.rows = rows or []

    def scalar_one(self) -> int:
        assert self.total is not None
        return self.total

    def scalars(self) -> "_EventResults":
        return self

    def all(self) -> list[Any]:
        return self.rows


class _EventSession:
    def __init__(self, event):
        self.event = event
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        if len(self.statements) == 1:
            return _EventResults(total=1)
        return _EventResults(rows=[self.event])


@pytest.mark.asyncio
async def test_events_filter_and_response_use_package_name() -> None:
    event = SimpleNamespace(
        id=1,
        event_type="log",
        package_name="com.example.app",
        device_id="device-1",
        sdk_version=None,
        payload={"extra": "raw"},
        client_ts=None,
        server_ts=None,
    )
    db = _EventSession(event)

    result = await get_events(
        db,  # type: ignore[arg-type]
        page=1,
        page_size=20,
        event_type=None,
        log_level=None,
        package_name="com.example.app",
        device_id=None,
        date_from=None,
        date_to=None,
    )

    assert result["items"][0]["package_name"] == "com.example.app"
    assert "app_id" not in result["items"][0]


@pytest.mark.asyncio
async def test_events_filter_by_log_level_and_include_sdk_version() -> None:
    event = SimpleNamespace(
        id=2,
        event_type="log",
        package_name="com.example.app",
        device_id="device-2",
        sdk_version="1.4.0",
        payload={"level": "error", "message": "boom"},
        client_ts=None,
        server_ts=None,
    )
    db = _EventSession(event)

    result = await get_events(
        db,  # type: ignore[arg-type]
        page=1,
        page_size=20,
        event_type=None,
        log_level="error",
        package_name=None,
        device_id=None,
        date_from=None,
        date_to=None,
    )

    compiled = db.statements[1].compile(dialect=postgresql.dialect())
    assert "sdk_events.event_type" in str(compiled)
    assert "sdk_events.payload ->>" in str(compiled)
    assert {"log", "level", "error"} <= set(compiled.params.values())
    assert result["items"][0]["sdk_version"] == "1.4.0"


@pytest.mark.asyncio
async def test_events_filter_dates_use_utc_plus_8_day_boundaries() -> None:
    event = SimpleNamespace(
        id=3,
        event_type="click",
        package_name="com.example.app",
        device_id="device-3",
        sdk_version=None,
        payload={},
        client_ts=None,
        server_ts=None,
    )
    db = _EventSession(event)

    await get_events(
        db,  # type: ignore[arg-type]
        page=1,
        page_size=20,
        event_type=None,
        log_level=None,
        package_name=None,
        device_id=None,
        date_from=date(2026, 8, 17),
        date_to=date(2026, 8, 17),
    )

    compiled = db.statements[1].compile(dialect=postgresql.dialect())
    assert datetime(2026, 8, 16, 16, tzinfo=timezone.utc) in compiled.params.values()
    assert datetime(2026, 8, 17, 16, tzinfo=timezone.utc) in compiled.params.values()


@pytest.mark.asyncio
async def test_breakdown_binds_utc_plus_8_business_day_boundaries() -> None:
    db = _CapturingSession()

    await get_breakdown(db, date(2026, 8, 17))  # type: ignore[arg-type]

    compiled = db.statement.compile(dialect=postgresql.dialect())
    assert datetime(2026, 8, 16, 16, tzinfo=timezone.utc) in compiled.params.values()
    assert datetime(2026, 8, 17, 16, tzinfo=timezone.utc) in compiled.params.values()


@pytest.mark.asyncio
async def test_events_serialize_timestamps_as_utc_plus_8_business_time() -> None:
    event = SimpleNamespace(
        id=4,
        event_type="click",
        package_name="com.example.app",
        device_id="device-4",
        sdk_version=None,
        payload={},
        client_ts=datetime(2026, 8, 17, 9, 59, tzinfo=timezone.utc),
        server_ts=datetime(2026, 8, 17, 10, tzinfo=timezone.utc),
    )
    db = _EventSession(event)

    result = await get_events(
        db,  # type: ignore[arg-type]
        page=1,
        page_size=20,
        event_type=None,
        log_level=None,
        package_name=None,
        device_id=None,
        date_from=None,
        date_to=None,
    )

    assert result["items"][0]["server_ts"] == "2026-08-17T18:00:00+08:00"
    assert result["items"][0]["client_ts"] == "2026-08-17T17:59:00+08:00"
