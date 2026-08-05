from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services import config_service


class FakeConfig:
    def __init__(self, *, config_id: int, version: str, status: str):
        self.id = config_id
        self.version = version
        self.status = status
        self.config_data = {"features": {"demo": True}}
        self.publish_at = None
        self.published_by = None
        self.cos_key = None
        self.cdn_url = None
        self.cos_upload_status = "pending"
        self.change_log = "local delivery"
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)


class FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class FakeDb:
    def __init__(self, config: FakeConfig):
        self.config = config
        self.committed = False
        self.executed = []

    async def get(self, _model, config_id):
        return self.config if config_id == self.config.id else None

    async def execute(self, stmt):
        self.executed.append(stmt)
        if "pg_try_advisory_xact_lock" in str(stmt):
            return FakeScalarResult(True)
        return FakeScalarResult(None)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        pass


@pytest.mark.anyio
async def test_publish_local_mode_skips_cos_upload_and_publishes(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("CONFIG_DELIVERY_MODE", "local")
    monkeypatch.setenv("CONFIG_META_LOCAL_BASE_URL", "https://sdk.deeppopgame.xyz")
    get_settings.cache_clear()

    draft = FakeConfig(config_id=2, version="draft_v2", status="draft")
    db = FakeDb(draft)

    def fail_if_cos_called(_cos_key: str, _json_bytes: bytes) -> str:
        raise AssertionError("local mode must not upload to COS")

    monkeypatch.setattr(config_service, "_upload_config_payload", fail_if_cos_called)

    result = await config_service.publish_config(db, 2, "admin")

    assert db.committed is True
    assert draft.status == "published"
    assert draft.cos_upload_status == "success"
    assert draft.cos_key == "local:config/latest.json"
    assert result["cdn_url"] == "https://sdk.deeppopgame.xyz/api/v1/config/latest"
    get_settings.cache_clear()
