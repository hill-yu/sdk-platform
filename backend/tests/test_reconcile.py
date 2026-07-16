from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.services import config_service


def _auth_headers(token: str = "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── Reconcile tests ──────────────────────────────────────────────────

class _FakeAsyncResponse:
    """模拟 httpx 响应"""
    def __init__(self, json_data: dict, status_code: int = 200):
        self._json_data = json_data
        self.status_code = status_code

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


class _FakeAsyncClient:
    """模拟 httpx.AsyncClient"""
    def __init__(self, response: _FakeAsyncResponse):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def get(self, url, **kwargs):
        return self._response


@pytest.mark.anyio
async def test_reconcile_latest_matches_db(monkeypatch):
    """对账: latest.json 版本与 DB 一致 → consistent=true"""
    from app.admin_main import app
    from app.api.admin import config_mgr as cm

    # 构造模拟 DB 返回
    class FakeConfig:
        id = 1
        version = "20260716_v120000_000001"
        status = "published"
        cos_upload_status = "success"
        cdn_url = "https://cdn.test.local/config/v20260716_v120000_000001.json"

    class FakeScalarResult:
        def scalar_one_or_none(self):
            return FakeConfig()

    class FakeReadSession:
        async def execute(self, *_args, **_kwargs):
            return FakeScalarResult()

    async def fake_get_db_no_commit():
        yield FakeReadSession()

    app.dependency_overrides[cm.get_db_no_commit] = fake_get_db_no_commit

    # Mock httpx 返回与 DB 一致的版本
    fake_response = _FakeAsyncResponse({"version": "20260716_v120000_000001"})
    fake_client = _FakeAsyncClient(fake_response)

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: fake_client)

    with TestClient(app) as client:
        resp = client.get("/api/admin/configs/reconcile", headers=_auth_headers())

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["consistent"] is True
    assert data["db_version"] == "20260716_v120000_000001"
    assert data["cdn_version"] == "20260716_v120000_000001"


@pytest.mark.anyio
async def test_reconcile_latest_mismatch(monkeypatch):
    """对账: latest.json 版本与 DB 不一致 → consistent=false"""
    from app.admin_main import app
    from app.api.admin import config_mgr as cm

    class FakeConfig:
        id = 1
        version = "20260716_v120000_000001"
        status = "published"
        cos_upload_status = "success"
        cdn_url = "https://cdn.test.local/config/v20260716_v120000_000001.json"

    class FakeScalarResult:
        def scalar_one_or_none(self):
            return FakeConfig()

    class FakeReadSession:
        async def execute(self, *_args, **_kwargs):
            return FakeScalarResult()

    async def fake_get_db_no_commit():
        yield FakeReadSession()

    app.dependency_overrides[cm.get_db_no_commit] = fake_get_db_no_commit

    # Mock httpx 返回不同的版本
    fake_response = _FakeAsyncResponse({"version": "20260715_v110000_000009"})
    fake_client = _FakeAsyncClient(fake_response)

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: fake_client)

    with TestClient(app) as client:
        resp = client.get("/api/admin/configs/reconcile", headers=_auth_headers())

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["consistent"] is False
    assert data["db_version"] == "20260716_v120000_000001"
    assert data["cdn_version"] == "20260715_v110000_000009"


# ── Commit failure persistence test ──────────────────────────────────

class FakeConfigForCommitFail:
    def __init__(self, *, config_id: int, version: str, status: str):
        self.id = config_id
        self.version = version
        self.status = status
        self.config_data = {"features": {}}
        self.publish_at = None
        self.published_by = None
        self.cos_key = None
        self.cdn_url = "https://cdn.test.local/config/latest.json"
        self.cos_upload_status = "pending"
        self.change_log = "init"
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)


class _FakeScalarResult:
    def __init__(self, scalar_value):
        self._scalar_value = scalar_value

    def scalar(self):
        return self._scalar_value


class FakeDbCommitFail:
    """commit 时抛异常，get 返回指定 config"""
    def __init__(self, config_for_recovery=None):
        self.executed = []
        self._config = config_for_recovery
        self.committed = False

    async def execute(self, stmt):
        self.executed.append(stmt)
        stmt_str = str(stmt)
        if "pg_try_advisory_xact_lock" in stmt_str:
            return _FakeScalarResult(True)
        return _FakeScalarResult(None)

    async def get(self, model, config_id):
        return self._config

    async def flush(self):
        pass

    async def commit(self):
        self.committed = True
        raise RuntimeError("simulated commit failure")

    async def rollback(self):
        pass

    def begin(self):
        return _FakeAsyncContextManager(self)


class _FakeAsyncContextManager:
    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *args):
        pass


@pytest.mark.anyio
async def test_commit_failure_persists_failed_status(monkeypatch):
    """数据库 commit 失败后，failed 状态被独立 session 持久化"""
    config = FakeConfigForCommitFail(config_id=1, version="draft_v1", status="draft")
    db = FakeDbCommitFail(config_for_recovery=config)

    # Mock COS 上传为成功
    def fake_upload(_cos_key: str, _json_bytes: bytes) -> str:
        return "https://cdn.test.local/config/test.json"

    monkeypatch.setattr(config_service, "_upload_config_payload", fake_upload)

    # Mock async_session_factory 返回 recovery session
    recovery_config = FakeConfigForCommitFail(config_id=1, version="draft_v1", status="draft")
    recovery_db = FakeDbCommitFail(config_for_recovery=recovery_config)
    # Override commit to succeed in recovery
    recovery_db.commit = lambda: None  # type: ignore
    recovery_db.committed = False

    fake_factory = type("FakeFactory", (), {"__call__": lambda self: _FakeAsyncContextManager(recovery_db)})()
    import app.core.database as db_module
    monkeypatch.setattr(db_module, "async_session_factory", fake_factory)

    # publish_config should raise HTTPException(500) after commit fails
    with pytest.raises(HTTPException) as exc_info:
        await config_service.publish_config(db, 1, "admin")

    assert exc_info.value.status_code == 500
    assert "CDN" in exc_info.value.detail

    # Recovery session should have persisted failed status
    assert recovery_config.cos_upload_status == "failed"
    assert "[COS_UPLOADED_DB_FAILED]" in (recovery_config.change_log or "")
