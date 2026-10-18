from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.database import get_db


TOKEN = "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0"


async def override_db():
    yield object()


def test_publish_timestamp_conflict_maps_to_409(monkeypatch):
    from app.admin_main import app
    from app.api.admin import config_mgr

    async def conflict(*_args, **_kwargs):
        raise config_mgr.config_service.ConfigPublishConflictError("配置已被其他操作修改")

    monkeypatch.setattr(config_mgr.config_service, "publish_config", conflict)
    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/admin/configs/501/publish",
                json={"expected_updated_at": "2026-10-18T04:00:00.123456Z"},
                headers={"Authorization": f"Bearer {TOKEN}"},
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 409
