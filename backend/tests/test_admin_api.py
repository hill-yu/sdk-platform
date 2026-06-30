from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def _auth_headers(token: str = "admin-secret-token-change-me") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_admin_summary_requires_bearer_token():
    from app.admin_main import app

    with TestClient(app) as client:
        response = client.get("/api/admin/dashboard/summary")

    assert response.status_code == 401


def test_admin_summary_returns_dashboard_payload(monkeypatch):
    from app.admin_main import app
    from app.api.admin import dashboard

    async def fake_summary(_db: Any) -> dict[str, int]:
        return {
            "today_pv": 12,
            "yesterday_pv": 10,
            "today_uv": 8,
            "yesterday_uv": 6,
            "today_events": 30,
            "yesterday_events": 20,
            "active_devices": 9,
            "yesterday_active_devices": 7,
            "error_count": 1,
        }

    monkeypatch.setattr(dashboard.analysis_service, "get_summary", fake_summary)

    with TestClient(app) as client:
        response = client.get("/api/admin/dashboard/summary", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json()["data"]["today_pv"] == 12
    assert response.json()["data"]["yesterday_pv"] == 10


def test_get_configs_returns_grouped_payload(monkeypatch):
    from app.admin_main import app
    from app.api.admin import config_mgr

    async def fake_list_configs(_db: Any) -> dict[str, Any]:
        return {
            "published": {"id": 1, "version": "20260630_v3"},
            "drafts": [{"id": 2, "version": "draft_001"}],
            "history": [{"id": 3, "version": "20260629_v2", "status": "archived"}],
        }

    monkeypatch.setattr(config_mgr.config_service, "list_configs", fake_list_configs)

    with TestClient(app) as client:
        response = client.get("/api/admin/configs", headers=_auth_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["published"]["version"] == "20260630_v3"


def test_publish_config_returns_publish_result(monkeypatch):
    from app.admin_main import app
    from app.api.admin import config_mgr

    async def fake_publish(_db: Any, config_id: int, published_by: str) -> dict[str, Any]:
        assert config_id == 6
        assert published_by == "admin"
        return {
            "version": "20260630_v3",
            "publish_at": "2026-06-30T10:35:00Z",
            "cdn_url": "https://cdn.example.com/config/latest.json",
            "cos_key": "config/v20260630_v3.json",
        }

    monkeypatch.setattr(config_mgr.config_service, "publish_config", fake_publish)

    with TestClient(app) as client:
        response = client.post("/api/admin/configs/6/publish", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json()["data"]["cdn_url"] == "https://cdn.example.com/config/latest.json"


def test_rollback_config_returns_publish_result(monkeypatch):
    from app.admin_main import app
    from app.api.admin import config_mgr

    async def fake_rollback(_db: Any, config_id: int, published_by: str) -> dict[str, Any]:
        assert config_id == 3
        assert published_by == "admin"
        return {
            "version": "20260629_v2",
            "publish_at": "2026-06-30T10:40:00Z",
            "cdn_url": "https://cdn.example.com/config/latest.json",
            "cos_key": "config/v20260629_v2.json",
            "message": "已回滚到版本 20260629_v2",
        }

    monkeypatch.setattr(config_mgr.config_service, "rollback_config", fake_rollback)

    with TestClient(app) as client:
        response = client.post("/api/admin/configs/3/rollback", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json()["data"]["message"] == "已回滚到版本 20260629_v2"


def test_version_list_returns_platform_versions(monkeypatch):
    from app.admin_main import app
    from app.api.admin import version_mgr

    async def fake_list_versions(_db: Any, platform: str | None) -> list[dict[str, Any]]:
        assert platform == "ios"
        return [{"id": 1, "platform": "ios", "version_code": 120, "version_name": "1.2.0"}]

    monkeypatch.setattr(version_mgr.version_service, "list_versions", fake_list_versions)

    with TestClient(app) as client:
        response = client.get("/api/admin/versions?platform=ios", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json()["data"][0]["version_code"] == 120


def test_version_update_passes_db_session_to_service(monkeypatch):
    from app.admin_main import app
    from app.api.admin import version_mgr

    async def fake_update(db: Any, version_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        assert db is not None
        assert version_id == 9
        assert payload["version_name"] == "1.2.1"
        return {"id": 9, "version_name": "1.2.1"}

    monkeypatch.setattr(version_mgr.version_service, "update_version", fake_update)

    with TestClient(app) as client:
        response = client.put(
            "/api/admin/versions/9",
            headers=_auth_headers(),
            json={"version_name": "1.2.1"},
        )

    assert response.status_code == 200
    assert response.json()["data"]["version_name"] == "1.2.1"
