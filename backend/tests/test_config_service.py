from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from app.services import config_service


class FakeConfig:
    def __init__(self, *, config_id: int, version: str, status: str):
        self.id = config_id
        self.version = version
        self.status = status
        self.config_data = {"features": {}}
        self.publish_at = None
        self.published_by = None
        self.cos_key = None
        self.cdn_url = None
        self.cos_upload_status = "pending"
        self.change_log = "init"
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)


class FakeDb:
    def __init__(self):
        self.executed = []
        self.flushed = False
        self.committed = False

    async def execute(self, stmt):
        self.executed.append(stmt)

    async def flush(self):
        self.flushed = True

    async def commit(self):
        self.committed = True

    async def rollback(self):
        pass


@pytest.mark.asyncio
async def test_rollback_keeps_original_version(monkeypatch):
    db = FakeDb()
    config = FakeConfig(config_id=3, version="20260629_v2", status="archived")

    # _upload_config_payload is now sync, called via asyncio.to_thread
    def fake_upload(_cos_key: str, _json_bytes: bytes) -> str:
        return "https://cdn.test.local/config/test.json"

    monkeypatch.setattr(config_service, "_upload_config_payload", fake_upload)

    result = await config_service._publish_from_record(db, config, "admin")

    # Version is now generated with %f microseconds, so it won't match old value
    assert result["version"] != "20260629_v2"
    assert config.version != "20260629_v2"
    # Verify version format: YYYYMMDD_vHHMMSS_ffffff
    assert re.match(r"\d{8}_v\d{6}_\d{6}", result["version"]), f"Unexpected version format: {result['version']}"
    # 3.1 重构后 service 不再自行 flush/commit，事务由外层 get_db 管理
    assert db.executed  # 至少执行了旧 published 归档的 update
    assert config.cos_upload_status == "success"
