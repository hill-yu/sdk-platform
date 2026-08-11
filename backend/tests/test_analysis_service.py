from __future__ import annotations

from typing import Any

import pytest

from app.services.analysis_service import get_trend


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
