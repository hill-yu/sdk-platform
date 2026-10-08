"""隔离 PostgreSQL 回归：解析 scope、H1 真零值与使用时长最新设备口径。"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.engine import make_url


pytestmark = pytest.mark.integration


def test_isolated_postgres_scope_and_usage_regression() -> None:
    database_url = os.environ.get("SDK_LOG_SCOPE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("SDK_LOG_SCOPE_TEST_DATABASE_URL is not set; real PostgreSQL regression unverified")
    parsed = make_url(database_url)
    if parsed.host not in {"127.0.0.1", "::1", "localhost"}:
        pytest.skip("integration database must be loopback")
    if not re.fullmatch(r"sdk_scope_test_[0-9a-f]{4,32}", parsed.database or ""):
        pytest.skip("integration database must use sdk_scope_test_<suffix>")

    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.database import Base
    from app.models.log_analysis import LogReparseJob
    from app.models.log_metrics import H1Declaration
    from app.models.usage_duration import SdkUsageDuration
    from app.services.log_metrics_service import get_overview
    from app.services.log_parse_job_service import get_latest_parse_job
    from app.services.usage_duration_service import get_usage_summary

    start = datetime(2026, 9, 29, tzinfo=timezone.utc)
    end = datetime(2026, 9, 30, tzinfo=timezone.utc)

    async def scenario() -> None:
        engine = create_async_engine(database_url)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.drop_all)
                await connection.run_sync(Base.metadata.create_all)
            async with session_factory() as session:
                older = LogReparseJob(
                    package_name="com.example.app", range_start=start, range_end=end,
                    snapshot_end=end - timedelta(minutes=2), status="success", created_at=start,
                    total_count=3, processed_count=3, h1_count=1,
                )
                newer = LogReparseJob(
                    package_name="com.example.app", range_start=start, range_end=end,
                    snapshot_end=end - timedelta(minutes=1), status="success", created_at=start + timedelta(minutes=1),
                    total_count=3, processed_count=3, h1_count=1,
                )
                overlap = LogReparseJob(
                    package_name="com.example.app", range_start=start + timedelta(hours=1), range_end=end,
                    snapshot_end=end, status="failed", created_at=start + timedelta(minutes=2),
                    total_count=3, processed_count=1, failed_count=2,
                )
                session.add_all([older, newer, overlap])
                session.add(H1Declaration(
                    event_id=101, event_server_ts=start + timedelta(hours=2), record_index=0,
                    package_name="com.example.app", device_id="device-1", declared_click_count=0,
                    status="success", decoder_version="test",
                ))
                session.add_all([
                    SdkUsageDuration(package_name="com.example.app", device_id="device-1", device_model="Pixel", os="14", app_version="1", sdk_version="1", duration_s=100, server_ts=start + timedelta(hours=1)),
                    SdkUsageDuration(package_name="com.example.app", device_id="device-1", device_model="Galaxy", os="14", app_version="1", sdk_version="1", duration_s=301, server_ts=start + timedelta(hours=2)),
                    SdkUsageDuration(package_name="com.example.app", device_id="device-2", device_model="iPhone", os="17", app_version="1", sdk_version="1", duration_s=900, server_ts=start + timedelta(hours=3)),
                ])
                await session.commit()

            async with session_factory() as session:
                latest = await get_latest_parse_job(session, package_name="com.example.app", range_start=start, range_end=end)
                assert latest is not None
                assert latest.snapshot_end == end - timedelta(minutes=1)
                overview = await get_overview(session, package_name="com.example.app", range_start=start, range_end=end)
                assert overview["declaration_count"] == 1
                assert overview["planned_click_count"] == 0
                assert overview["actual_click_count"] == 0
                assert overview["response_success_count"] == 0
                summary = await get_usage_summary(session, package_name="com.example.app", range_start=start, range_end=end, page=1, page_size=20, sort_by="device_model", sort_order="asc")
                assert summary["total"] == 1
                item = summary["items"][0]
                assert item["device_model"] is None
                assert item["device_count"] == 2
                assert item["total_duration_s"] == 1201
                assert [bucket["count"] for bucket in item["buckets"]] == [0, 1, 0, 1]
        finally:
            await engine.dispose()

    asyncio.run(scenario())
