"""Real PostgreSQL paging evidence for usage device details."""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import insert, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = pytest.mark.integration


def _database_url() -> str:
    value = os.environ.get("SDK_USAGE_DURATION_TEST_DATABASE_URL")
    if not value:
        pytest.skip("SDK_USAGE_DURATION_TEST_DATABASE_URL is not set")
    parsed = make_url(value)
    if parsed.host not in {"127.0.0.1", "::1", "localhost"}:
        pytest.skip("integration database must be loopback")
    if not re.fullmatch(r"sdk_usage_duration_test_[0-9a-f]{4,32}", parsed.database or ""):
        pytest.skip("integration database must use sdk_usage_duration_test_<suffix>")
    return value


@pytest.mark.asyncio
async def test_usage_devices_pages_25_latest_rows_with_os_and_exact_total() -> None:
    database_url = _database_url()
    from app.models.usage_duration import SdkUsageDuration
    from app.services.usage_duration_service import get_usage_devices, get_usage_summary

    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    start = datetime(2026, 9, 28, tzinfo=timezone.utc)
    end = datetime(2026, 10, 1, tzinfo=timezone.utc)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(SdkUsageDuration.__table__.create, checkfirst=True)
            await connection.execute(text("TRUNCATE sdk_usage_durations"))
        rows = []
        for index in range(25):
            device_id = f"device-{index:02d}"
            older = start + timedelta(minutes=index)
            latest = start + timedelta(days=1, minutes=index)
            rows.extend([
                {"id": index * 2 + 1, "package_name": "com.integration.app", "device_id": device_id, "device_model": "Pixel", "os": "13", "app_version": "1.0", "sdk_version": "1.0", "duration_s": 100, "server_ts": older},
                {"id": index * 2 + 2, "package_name": "com.integration.app", "device_id": device_id, "device_model": "Pixel", "os": "14", "app_version": "1.1", "sdk_version": "1.1", "duration_s": 200 + index, "server_ts": latest},
            ])
        async with sessions() as session:
            async with session.begin():
                await session.execute(insert(SdkUsageDuration), rows)
            summary = await get_usage_summary(
                session,
                package_name="com.integration.app",
                range_start=start,
                range_end=end,
                page=1,
                page_size=10,
                sort_by="package_name",
                sort_order="asc",
            )
            pages = [
                await get_usage_devices(session, package_name="com.integration.app", device_model=None, range_start=start, range_end=end, page=page, page_size=10)
                for page in (1, 2, 3)
            ]
        assert summary["total"] == 1
        assert summary["total_pages"] == 1
        summary_item = summary["items"][0]
        assert summary_item["device_count"] == 25
        assert summary_item["total_duration_s"] == sum(200 + index for index in range(25))
        assert summary_item["average_duration_s"] == 212
        assert summary_item["buckets"][1]["count"] == 25
        assert summary_item["buckets"][1]["total_duration_s"] == 5300
        assert summary_item["buckets"][1]["share"] == 1.0
        assert summary_item["total_duration_text"] == "1 小时 28 分 20 秒"
        assert summary_item["buckets"][1]["share_text"] == "100.0%"
        assert [page["total"] for page in pages] == [25, 25, 25]
        assert [page["total_pages"] for page in pages] == [3, 3, 3]
        assert [len(page["items"]) for page in pages] == [10, 10, 5]
        items = [item for page in pages for item in page["items"]]
        assert [item["device_id"] for item in items] == [f"device-{index:02d}" for index in range(24, -1, -1)]
        assert {item["os"] for item in items} == {"14"}
        assert items[0]["duration_s"] == 224
        assert items[0]["duration_text"] == "3 分 44 秒"
        assert items[0]["last_report_text"] == "2026-09-29T08:24:00+08:00"
        assert items[-1]["duration_s"] == 200
    finally:
        await engine.dispose()
