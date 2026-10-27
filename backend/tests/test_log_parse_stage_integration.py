from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.event import SdkEvent
from app.models.log_analysis import LogReparseJob
from app.models.log_metrics import H1DeclarationStage, LogClickAttemptStage
from app.services import log_parse_job_service as service


pytestmark = pytest.mark.integration


def _database_url() -> str:
    value = os.environ.get("SDK_PARSE_STAGE_TEST_DATABASE_URL")
    if not value:
        pytest.skip("SDK_PARSE_STAGE_TEST_DATABASE_URL is not set; isolated PostgreSQL regression unverified")
    parsed = make_url(value)
    host = parsed.host
    if host not in {"127.0.0.1", "localhost", "::1"}:
        pytest.skip("SDK_PARSE_STAGE_TEST_DATABASE_URL must point to a dedicated loopback PostgreSQL database")
    if parsed.database is None or not re.fullmatch(r"sdk_parse_stage_test_[0-9a-f]{4,32}", parsed.database):
        pytest.skip("SDK_PARSE_STAGE_TEST_DATABASE_URL must use a database named sdk_parse_stage_test_[0-9a-f]{4,32}")
    if parsed.database in {"sdk_platform", "postgres", "template0", "template1"}:
        pytest.skip("production and template databases are not permitted for this regression")
    return value


def _click_row(index: int) -> dict[str, object]:
    return {
        "job_id": 880,
        "event_id": index + 1,
        "event_server_ts": datetime(2026, 10, 9, tzinfo=timezone.utc) + timedelta(seconds=index),
        "record_index": 1,
        "attempt_index": index + 1,
        "package_name": "integration.pkg",
        "config_id": 1,
        "target_kind": "target",
        "did_click": True,
        "navigation_code": 1,
        "reason": None,
        "error_detail": None,
        "navigation_result": None,
        "failure_category": None,
        "click_timestamp": None,
        "page_context": None,
        "decoder_version": "2.0.0",
    }


def _h1_row(index: int) -> dict[str, object]:
    return {
        "job_id": 880,
        "event_id": index + 1,
        "event_server_ts": datetime(2026, 10, 9, tzinfo=timezone.utc) + timedelta(seconds=index),
        "record_index": 1,
        "package_name": "integration.pkg",
        "device_id": "d",
        "sdk_version": "1",
        "config_id": 1,
        "window": "old",
        "declared_click_count": 18,
        "interstitial_presentation_count": 0,
        "interstitial_click_count": 0,
        "interstitial_close_count": 0,
        "flow_duration_ms": 1,
        "final_reason": "old",
        "status": "success",
        "parse_error": None,
        "decoder_version": "2.0.0",
        "parsed_at": datetime(2026, 10, 9, tzinfo=timezone.utc),
        "decoded_payload": {"integration": True},
    }


@pytest.mark.asyncio
async def test_parse_stage_chunking_and_process_failure_rollback() -> None:
    database_url = _database_url()
    engine = create_async_engine(database_url)
    tables = [SdkEvent.__table__, LogReparseJob.__table__, H1DeclarationStage.__table__, LogClickAttemptStage.__table__]
    base = datetime(2026, 10, 9, tzinfo=timezone.utc)
    extra = "H1|i=GC|p=18|pa=" + ",".join(["b11hfn1"] * 18)

    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
            Session = async_sessionmaker(bind=connection, expire_on_commit=False)

            async with Session() as session:
                await service._insert_stage_rows_in_chunks(
                    session,
                    H1DeclarationStage,
                    [_h1_row(index) for index in range(1833)],
                )
                await service._insert_stage_rows_in_chunks(
                    session,
                    LogClickAttemptStage,
                    [_click_row(index) for index in range(3590)],
                )
                assert await session.scalar(select(func.count()).select_from(H1DeclarationStage).where(H1DeclarationStage.job_id == 880)) == 1833
                assert await session.scalar(select(func.count()).select_from(LogClickAttemptStage)) == 3590

                job = LogReparseJob(
                    id=991,
                    package_name="integration.pkg",
                    range_start=base,
                    range_end=base + timedelta(days=1),
                    snapshot_end=base + timedelta(days=1),
                    status="running",
                    lease_owner="integration-worker",
                    lease_expires_at=base + timedelta(hours=1),
                    batch_size=200,
                    concurrency=1,
                    total_count=200,
                    processed_count=0,
                    h1_count=0,
                    failed_h1_count=0,
                    no_h1_count=0,
                    last_heartbeat_at=base,
                )
                session.add(job)
                events = [
                    SdkEvent(
                        event_type="log",
                        package_name="integration.pkg",
                        device_id="d",
                        sdk_version="1",
                        server_ts=base + timedelta(seconds=index),
                        payload={"extra": extra},
                    )
                    for index in range(200)
                ]
                session.add_all(events)
                await session.flush()
                await session.execute(
                    H1DeclarationStage.__table__.insert().values(
                        {
                            "job_id": 991,
                            "event_id": events[0].id,
                            "event_server_ts": events[0].server_ts,
                            "record_index": 1,
                            "package_name": "integration.pkg",
                            "device_id": "d",
                            "sdk_version": "1",
                            "config_id": 1,
                            "window": "old",
                            "declared_click_count": 1,
                            "interstitial_presentation_count": 0,
                            "interstitial_click_count": 0,
                            "interstitial_close_count": 0,
                            "flow_duration_ms": 1,
                            "final_reason": "old",
                            "status": "success",
                            "parse_error": None,
                            "decoder_version": "old",
                            "parsed_at": base,
                            "decoded_payload": {"old": True},
                        }
                    )
                )
                await session.execute(
                    LogClickAttemptStage.__table__.insert().values(
                        {
                            **_click_row(0),
                            "job_id": 991,
                            "event_id": events[0].id,
                            "event_server_ts": events[0].server_ts,
                            "attempt_index": 1,
                        }
                    )
                )
                await session.flush()

                original_helper = service._insert_stage_rows_in_chunks
                original_factory = service.PARSE_EXECUTOR_FACTORY

                async def fail_on_second_click_chunk(db, model, rows):
                    if model is LogClickAttemptStage and len(rows) > 1000:
                        await original_helper(db, model, rows[:1000])
                        raise RuntimeError("injected second chunk failure")
                    await original_helper(db, model, rows)

                service._insert_stage_rows_in_chunks = fail_on_second_click_chunk
                service.PARSE_EXECUTOR_FACTORY = ThreadPoolExecutor
                try:
                    with pytest.raises(RuntimeError, match="second chunk"):
                        async with session.begin_nested():
                            await service.process_parse_job_batch(
                                session,
                                991,
                                worker_id="integration-worker",
                                now=base + timedelta(minutes=1),
                                batch_size=200,
                            )
                finally:
                    service._insert_stage_rows_in_chunks = original_helper
                    service.PARSE_EXECUTOR_FACTORY = original_factory

                session.expire_all()
                current_job = await session.get(LogReparseJob, 991)
                assert await session.scalar(select(func.count()).select_from(H1DeclarationStage).where(H1DeclarationStage.job_id == 991)) == 1
                assert await session.scalar(select(func.count()).select_from(LogClickAttemptStage).where(LogClickAttemptStage.job_id == 991)) == 1
                assert current_job.processed_count == 0
                assert current_job.h1_count == 0
                assert current_job.failed_h1_count == 0
                assert current_job.no_h1_count == 0
                assert current_job.cursor_event_id is None
                assert current_job.cursor_server_ts is None
                assert current_job.lease_owner == "integration-worker"
                assert current_job.lease_expires_at == base + timedelta(hours=1)
                assert current_job.last_heartbeat_at == base
        finally:
            await transaction.rollback()

    await engine.dispose()
