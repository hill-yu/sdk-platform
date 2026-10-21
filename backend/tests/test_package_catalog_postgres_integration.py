"""Real PostgreSQL evidence for package catalog correctness and query isolation."""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = pytest.mark.integration


def _database_url() -> str:
    value = os.environ.get("SDK_PACKAGE_CATALOG_TEST_DATABASE_URL")
    if not value:
        pytest.skip("SDK_PACKAGE_CATALOG_TEST_DATABASE_URL is not set")
    parsed = make_url(value)
    if parsed.host not in {"127.0.0.1", "::1", "localhost"}:
        pytest.skip("integration database must be loopback")
    if not re.fullmatch(r"sdk_package_catalog_test_[0-9a-f]{4,32}", parsed.database or ""):
        pytest.skip("integration database must use sdk_package_catalog_test_<suffix>")
    return value


@pytest.mark.asyncio
async def test_package_catalog_concurrency_rollback_noop_and_plan_isolation():
    database_url = _database_url()
    from app.models.package_catalog import PackageCatalog
    from app.services.package_catalog_service import ensure_package_sources, search_packages

    engine = create_async_engine(database_url, pool_size=5, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            await connection.run_sync(PackageCatalog.__table__.create, checkfirst=True)
            await connection.execute(text("TRUNCATE sdk_package_catalog"))

        async def write_source(flag: str) -> None:
            async with sessions() as session:
                async with session.begin():
                    await ensure_package_sources(session, ["com.concurrent.app"], **{flag: True})

        await asyncio.gather(write_source("has_log"), write_source("has_usage"))
        async with sessions() as session:
            row = (
                await session.execute(
                    text("SELECT has_log, has_usage, updated_at FROM sdk_package_catalog WHERE package_name=:name"),
                    {"name": "com.concurrent.app"},
                )
            ).mappings().one()
            before_updated_at = row["updated_at"]
            assert row["has_log"] is True
            assert row["has_usage"] is True
            await ensure_package_sources(session, ["com.concurrent.app"], has_log=True, has_usage=True)
            after_updated_at = (
                await session.execute(
                    text("SELECT updated_at FROM sdk_package_catalog WHERE package_name=:name"),
                    {"name": "com.concurrent.app"},
                )
            ).scalar_one()
            assert after_updated_at == before_updated_at

        async with sessions() as session:
            try:
                async with session.begin():
                    await ensure_package_sources(session, ["com.rollback.app"], has_log=True)
                    raise RuntimeError("rollback probe")
            except RuntimeError:
                pass
        async with sessions() as session:
            assert (
                await session.execute(
                    text("SELECT 1 FROM sdk_package_catalog WHERE package_name='com.rollback.app'")
                )
            ).scalar_one_or_none() is None

        async with sessions() as session:
            await ensure_package_sources(session, ["com.log.only"], has_log=True)
            await ensure_package_sources(session, ["com.usage.only"], has_usage=True)
            await session.commit()
            start = time.perf_counter()
            assert await search_packages(session, None, 20, source="log") == ["com.concurrent.app", "com.log.only"]
            assert await search_packages(session, "usage", 20, source="usage") == ["com.usage.only"]
            assert await search_packages(session, "does-not-exist", 20, source="log") == []
            elapsed_ms = (time.perf_counter() - start) * 1000
            plan = (
                await session.execute(
                    text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT package_name FROM sdk_package_catalog WHERE has_log IS TRUE AND package_name ILIKE '%log%' ORDER BY package_name LIMIT 20")
                )
            ).scalar_one()
            plan_text = json.dumps(plan)
            assert "sdk_events" not in plan_text
            assert "sdk_usage_durations" not in plan_text
            assert elapsed_ms < 1000
    finally:
        await engine.dispose()
