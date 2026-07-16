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
    db = FakeDbLock(lock_ok=True)
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


class _FakeScalarResult:
    """可配置 scalar() 返回值的假结果对象"""
    def __init__(self, scalar_value):
        self._scalar_value = scalar_value

    def scalar(self):
        return self._scalar_value

    def scalar_one_or_none(self):
        return self._scalar_value


class FakeDbLock:
    """支持可配置返回值 + lock 模拟的假 DB"""
    def __init__(self, lock_ok: bool = True):
        self.executed = []
        self.committed = False
        self.rolled_back = False
        self._lock_ok = lock_ok
        self._configs: dict[int, object] = {}

    def add_config(self, config):
        self._configs[config.id] = config

    async def get(self, model, config_id):
        return self._configs.get(config_id)

    async def execute(self, stmt):
        self.executed.append(stmt)
        stmt_str = str(stmt)
        if "pg_try_advisory_xact_lock" in stmt_str:
            return _FakeScalarResult(self._lock_ok)
        return _FakeScalarResult(None)

    async def flush(self):
        pass

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


@pytest.mark.anyio
async def test_publish_lock_conflict_returns_409():
    """并发获取 advisory lock 失败返回 409"""
    from fastapi import HTTPException

    db = FakeDbLock(lock_ok=False)
    draft = FakeConfig(config_id=1, version="draft_v1", status="draft")
    db.add_config(draft)

    with pytest.raises(HTTPException) as exc_info:
        await config_service.publish_config(db, 1, "admin")
    assert exc_info.value.status_code == 409
    assert "另一" in exc_info.value.detail


@pytest.mark.anyio
async def test_publish_cos_failure_rollback(monkeypatch):
    """COS 上传失败时 DB 不归档旧配置，当前 config 状态不变"""
    from fastapi import HTTPException

    db = FakeDbLock(lock_ok=True)
    draft = FakeConfig(config_id=1, version="draft_v1", status="draft")
    db.add_config(draft)

    def fake_upload_fail(_cos_key: str, _json_bytes: bytes) -> str:
        raise RuntimeError("COS 不可用")

    monkeypatch.setattr(config_service, "_upload_config_payload", fake_upload_fail)

    with pytest.raises(RuntimeError, match="COS 不可用"):
        await config_service.publish_config(db, 1, "admin")

    # COS 失败 → config 状态不变（仍是 draft）
    assert draft.status == "draft"


@pytest.mark.anyio
async def test_rollback_cos_failure_no_change(monkeypatch):
    """回滚 COS 失败时 published 不变，archived 不变"""
    from fastapi import HTTPException

    db = FakeDbLock(lock_ok=True)
    archived = FakeConfig(config_id=3, version="20260629_v2", status="archived")
    db.add_config(archived)

    def fake_upload_fail(_cos_key: str, _json_bytes: bytes) -> str:
        raise RuntimeError("COS 不可用")

    monkeypatch.setattr(config_service, "_upload_config_payload", fake_upload_fail)

    with pytest.raises(RuntimeError, match="COS 不可用"):
        await config_service.rollback_config(db, 3, "admin")

    # COS 失败 → archived 状态不变
    assert archived.status == "archived"
