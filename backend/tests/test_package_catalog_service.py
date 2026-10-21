from __future__ import annotations

import pytest


class Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def scalars(self):
        return self


class RecordingSession:
    def __init__(self, existing=()):
        self.existing = list(existing)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        if statement.is_select:
            return Result(self.existing)
        return Result([])


@pytest.mark.asyncio
async def test_existing_source_is_read_without_catalog_update():
    from app.services.package_catalog_service import ensure_package_sources

    session = RecordingSession([{"package_name": "com.example.app", "has_log": True, "has_usage": False}])
    changed = await ensure_package_sources(session, [" com.example.app "], has_log=True)

    assert changed == []
    assert len(session.statements) == 1
    assert session.statements[0].is_select


@pytest.mark.asyncio
async def test_missing_source_uses_conditional_upsert_and_deduplicates_names():
    from app.services.package_catalog_service import ensure_package_sources

    session = RecordingSession([{"package_name": "com.example.app", "has_log": True, "has_usage": False}])
    changed = await ensure_package_sources(session, ["com.example.app", " com.example.app ", "com.other"], has_usage=True)

    assert changed == ["com.example.app", "com.other"]
    assert len(session.statements) == 2
    upsert = session.statements[1]
    sql = str(upsert.compile(dialect=upsert._dialect if hasattr(upsert, "_dialect") else None)).lower()
    assert "on conflict" in sql
    assert "where" in sql
    assert "updated_at" in sql


@pytest.mark.asyncio
async def test_search_uses_selected_source_and_preserves_limit_ordering():
    from app.services.package_catalog_service import search_packages

    session = RecordingSession()
    await search_packages(session, " com ", 20, source="usage")
    statement = session.statements[0]
    sql = str(statement.compile(compile_kwargs={"literal_binds": True})).lower()
    assert "sdk_package_catalog" in sql
    assert "has_usage" in sql
    assert "like lower('%com%')" in sql
    assert "order by sdk_package_catalog.package_name" in sql
    assert "limit 20" in sql
    assert "sdk_events" not in sql
    assert "sdk_usage_durations" not in sql


@pytest.mark.asyncio
async def test_invalid_source_is_rejected():
    from app.services.package_catalog_service import search_packages

    with pytest.raises(ValueError, match="source"):
        await search_packages(RecordingSession(), None, 20, source="click")
