"""Reproducible PostgreSQL isolation checks for history and publish preconditions.

Run only against a disposable database whose name starts with ``sdk_log_history_test_``:
``$env:SDK_LOG_HISTORY_TEST_DATABASE_URL='postgresql+asyncpg://...'; python -m pytest backend/tests/test_log_history_postgres_integration.py -q``.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import event, insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.admin_main import app
from app.api.admin.deps import require_admin_token
from app.core.database import get_db_no_commit
from app.models.log_analysis import LogReparseJob
from app.models.log_metrics import H1Declaration, H1DeclarationStage, LogClickAttempt, LogClickAttemptStage
from app.services.log_history_service import get_complete_job_context
from app.services.log_metrics_service import (
    get_config_breakdown,
    get_failure_breakdown,
    get_h1_details,
    get_overview,
    get_target_breakdown,
)


URL = os.getenv("SDK_LOG_HISTORY_TEST_DATABASE_URL")
if not URL:
    pytest.skip("SDK_LOG_HISTORY_TEST_DATABASE_URL is not set", allow_module_level=True)
if "sdk_log_history_test_" not in URL.rsplit("/", 1)[-1]:
    pytest.skip("history integration URL must point to a dedicated sdk_log_history_test_* database", allow_module_level=True)

START = datetime(2026, 9, 29, tzinfo=timezone.utc)
END = datetime(2026, 9, 30, tzinfo=timezone.utc)


@pytest.fixture
async def db():
    engine = create_async_engine(URL)
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: LogReparseJob.__table__.create(sync, checkfirst=True))
        await connection.run_sync(lambda sync: H1DeclarationStage.__table__.create(sync, checkfirst=True))
        await connection.run_sync(lambda sync: LogClickAttemptStage.__table__.create(sync, checkfirst=True))
        await connection.run_sync(lambda sync: H1Declaration.__table__.create(sync, checkfirst=True))
        await connection.run_sync(lambda sync: LogClickAttempt.__table__.create(sync, checkfirst=True))
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(lambda sync: LogClickAttemptStage.__table__.drop(sync, checkfirst=True))
            await connection.run_sync(lambda sync: H1DeclarationStage.__table__.drop(sync, checkfirst=True))
            await connection.run_sync(lambda sync: LogClickAttempt.__table__.drop(sync, checkfirst=True))
            await connection.run_sync(lambda sync: H1Declaration.__table__.drop(sync, checkfirst=True))
            await connection.run_sync(lambda sync: LogReparseJob.__table__.drop(sync, checkfirst=True))
        await engine.dispose()


async def seed(session):
    await session.execute(insert(LogReparseJob), [
        dict(id=101, package_name="com.example.app", range_start=START, range_end=END, snapshot_end=END, status="success", processed_count=1, total_count=1, h1_count=1, failed_h1_count=0, no_h1_count=0),
        dict(id=102, package_name="com.example.app", range_start=START, range_end=END, snapshot_end=END, status="success", processed_count=1, total_count=1, h1_count=1, failed_h1_count=0, no_h1_count=0),
    ])
    await session.execute(insert(H1DeclarationStage), [
        dict(job_id=101, event_id=1, event_server_ts=START, record_index=0, package_name="com.example.app", status="success", decoder_version="test", decoded_payload={"planned_click_attempts": [{}]}),
        dict(job_id=102, event_id=1, event_server_ts=START, record_index=0, package_name="com.example.app", status="success", decoder_version="test", decoded_payload={"planned_click_attempts": [{}]}),
    ])
    await session.execute(insert(LogClickAttemptStage), [
        dict(job_id=101, event_id=1, event_server_ts=START, record_index=0, attempt_index=0, package_name="com.example.app", target_kind="web_element", did_click=True, navigation_code=1, decoder_version="test"),
        dict(job_id=102, event_id=1, event_server_ts=START, record_index=0, attempt_index=0, package_name="com.example.app", target_kind="web_element", did_click=False, navigation_code=0, failure_category="timeout", decoder_version="test"),
    ])
    # Simulate the later formal-table overwrite for package B. Historical reads
    # must remain pinned to the stage rows for each job instead of falling back.
    await session.execute(insert(H1Declaration), [
        dict(event_id=1, event_server_ts=START, record_index=0, package_name="com.example.app", status="success", decoder_version="formal-overwrite", decoded_payload={"planned_click_attempts": [{}]}),
    ])
    await session.execute(insert(LogClickAttempt), [
        dict(event_id=1, event_server_ts=START, record_index=0, attempt_index=0, package_name="com.example.app", target_kind="web_element", did_click=True, navigation_code=1, decoder_version="formal-overwrite"),
    ])
    await session.commit()


@pytest.mark.anyio
async def test_two_successful_jobs_are_isolated_across_all_history_metric_surfaces(db):
    await seed(db)
    statements: list[str] = []
    event.listen(db.bind.sync_engine, "before_cursor_execute", lambda *_args: statements.append(_args[2]))
    common = dict(package_name="com.example.app", range_start=START, range_end=END)
    for job_id in (101, 102):
        context = await get_complete_job_context(db, job_id)
        assert context.id == job_id
        h1 = dict(**common, h1_model=H1DeclarationStage, job_id=job_id)
        click = dict(**common, click_model=LogClickAttemptStage, job_id=job_id)
        overview = await get_overview(db, **h1, click_model=LogClickAttemptStage)
        await get_config_breakdown(db, **h1)
        await get_target_breakdown(db, **click)
        await get_failure_breakdown(db, **click)
        await get_h1_details(db, **h1, click_model=LogClickAttemptStage)
        assert overview["actual_click_count"] == (1 if job_id == 101 else 0)
    sql = "\n".join(statements)
    assert "sdk_log_h1_declarations" not in sql and "sdk_log_click_attempts" not in sql
    assert "sdk_log_h1_declaration_stage" in sql and "sdk_log_click_attempt_stage" in sql
    assert sql.count("job_id") >= 10


@pytest.mark.anyio
async def test_http_history_metrics_use_job_id_and_reject_unavailable_jobs(db):
    await seed(db)
    await db.execute(insert(LogReparseJob), [
        dict(id=103, package_name="com.example.app", range_start=START, range_end=END, snapshot_end=END, status="failed", processed_count=0, total_count=1, h1_count=0, failed_h1_count=0, no_h1_count=0),
        dict(id=104, package_name="com.example.app", range_start=START, range_end=END, snapshot_end=END, status="success", processed_count=0, total_count=1, h1_count=0, failed_h1_count=0, no_h1_count=0),
    ])
    await db.commit()

    async def override_db():
        yield db

    async def override_admin():
        return "test-admin"

    app.dependency_overrides[get_db_no_commit] = override_db
    app.dependency_overrides[require_admin_token] = override_admin
    statements: list[str] = []
    listener = lambda *_args: statements.append(_args[2])
    event.listen(db.bind.sync_engine, "before_cursor_execute", listener)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            paths = ["overview", "configs", "targets", "failures", "h1"]
            for metric in paths:
                response = await client.get(f"/api/admin/log-analysis/parse-jobs/101/metrics/{metric}")
                assert response.status_code == 200, (metric, response.text)
                assert response.json()["code"] == 0
            for metric in paths:
                response = await client.get(f"/api/admin/log-analysis/parse-jobs/102/metrics/{metric}")
                assert response.status_code == 200, (metric, response.text)
                assert response.json()["code"] == 0
            overview_a = (await client.get("/api/admin/log-analysis/parse-jobs/101/metrics/overview")).json()["data"]
            overview_b = (await client.get("/api/admin/log-analysis/parse-jobs/102/metrics/overview")).json()["data"]
            assert overview_a["actual_click_count"] == 1
            assert overview_b["actual_click_count"] == 0

            assert (await client.get("/api/admin/log-analysis/parse-jobs/999/metrics/overview")).status_code == 404
            assert (await client.get("/api/admin/log-analysis/parse-jobs/103/metrics/overview")).status_code == 409
            assert (await client.get("/api/admin/log-analysis/parse-jobs/104/metrics/overview")).status_code == 409
            sql = "\n".join(statements)
            assert "sdk_log_h1_declarations" not in sql and "sdk_log_click_attempts" not in sql
            assert "sdk_log_h1_declaration_stage" in sql and "sdk_log_click_attempt_stage" in sql
            assert "job_id" in sql
    finally:
        event.remove(db.bind.sync_engine, "before_cursor_execute", listener)
        app.dependency_overrides.pop(get_db_no_commit, None)
        app.dependency_overrides.pop(require_admin_token, None)
