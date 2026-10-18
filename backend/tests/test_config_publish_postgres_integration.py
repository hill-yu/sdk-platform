"""Two-connection PostgreSQL publish-precondition check.

Run against a disposable database named ``sdk_config_publish_test_*`` with
``SDK_CONFIG_PUBLISH_TEST_DATABASE_URL``.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models.config import SdkConfig
from app.services.config_crypto import encrypt_payload
from app.services.config_service import ConfigPublishConflictError, publish_config, update_config


URL = os.getenv("SDK_CONFIG_PUBLISH_TEST_DATABASE_URL")
if not URL:
    pytest.skip("SDK_CONFIG_PUBLISH_TEST_DATABASE_URL is not set", allow_module_level=True)
if "sdk_config_publish_test_" not in URL.rsplit("/", 1)[-1]:
    pytest.skip("publish integration URL must point to a dedicated sdk_config_publish_test_* database", allow_module_level=True)


@pytest.mark.anyio
async def test_save_holding_row_lock_invalidates_preview_without_publish_side_effects(monkeypatch):
    monkeypatch.setenv("CONFIG_DELIVERY_MODE", "local")
    monkeypatch.setenv("SDK_CONFIG_TOKEN", "integration-config-token-1234567890")
    get_settings.cache_clear()
    engine = create_async_engine(URL)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    data = {"mainConfig": {}, "newTouchConfig": {}, "newTextRuleConfig": {}}
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: SdkConfig.__table__.create(sync, checkfirst=True))
    try:
        async with Session() as seed:
            await seed.execute(insert(SdkConfig).values(id=501, package_name="com.example.app", version="draft_1", encrypted_config=encrypt_payload(data, "com.example.app", "draft_1", "full", "integration-config-token-1234567890"), encryption_key_id="v1", status="draft", change_log="initial", cos_upload_status="pending", updated_at=datetime.now(timezone.utc)))
            await seed.commit()
        async with Session() as preview, Session() as saver, Session() as publisher:
            preview_row = await preview.get(SdkConfig, 501)
            expected = preview_row.updated_at
            await update_config(saver, 501, {**data, "mainConfig": {"saved": True}}, "saved")
            assert expected != (await saver.get(SdkConfig, 501)).updated_at
            publish_task = asyncio.create_task(publish_config(publisher, 501, "admin", expected_updated_at=expected))
            await asyncio.sleep(0.05)
            assert not publish_task.done(), "publish must wait for the save row lock"
            await saver.commit()
            with pytest.raises(ConfigPublishConflictError):
                await publish_task
        async with Session() as check:
            row = await check.get(SdkConfig, 501)
            assert row.status == "draft"
            assert row.version == "draft_1"
            assert row.cos_upload_status == "pending"
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(lambda sync: SdkConfig.__table__.drop(sync, checkfirst=True))
        await engine.dispose()
        get_settings.cache_clear()
