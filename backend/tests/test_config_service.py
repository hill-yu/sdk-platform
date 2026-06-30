from __future__ import annotations

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
        self.change_log = "init"
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)


class FakeDb:
    def __init__(self):
        self.executed = []
        self.flushed = False

    async def execute(self, stmt):
        self.executed.append(stmt)

    async def flush(self):
        self.flushed = True


@pytest.mark.asyncio
async def test_rollback_keeps_original_version(monkeypatch):
    db = FakeDb()
    config = FakeConfig(config_id=3, version="20260629_v2", status="archived")

    async def fake_upload(_cos_key: str, _payload: dict):
        return None

    monkeypatch.setattr(config_service, "_upload_config_payload", fake_upload)

    result = await config_service._publish_from_record(db, config, "admin")

    assert result["version"] == "20260629_v2"
    assert config.version == "20260629_v2"
    assert db.flushed is True
