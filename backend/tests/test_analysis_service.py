from __future__ import annotations

from typing import Any

import pytest

from types import SimpleNamespace

from app.services.analysis_service import get_events, get_trend
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

    async def execute(self, statement: Any, params: dict[str, Any]) -> _Rows:
        self.statement = statement
        self.params = params
        return _Rows()


@pytest.mark.asyncio
@pytest.mark.parametrize("range_value", ["24h", "7d"])
async def test_trend_sql_binds_the_complete_event_type_parameter(range_value: str) -> None:
    db = _CapturingSession()

    await get_trend(db, range_value=range_value, event_type=None)  # type: ignore[arg-type]

    assert "event_type" in db.statement._bindparams
    assert "event_typ" not in db.statement._bindparams
    assert ":event_type::varchar" not in str(db.statement)


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
