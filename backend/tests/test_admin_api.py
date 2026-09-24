from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient


def _auth_headers(token: str = "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class _CommitSession:
    def __init__(self):
        self.committed = False

    async def commit(self):
        self.committed = True

    async def rollback(self):
        pass


def test_package_profile_update_rejects_empty_object():
    from app.admin_main import app

    with TestClient(app) as client:
        response = client.put(
            "/api/admin/package-profiles/com.example.app",
            headers=_auth_headers(),
            json={},
        )

    assert response.status_code == 422


def test_package_profile_update_accepts_explicit_empty_string(monkeypatch):
    from app.admin_main import app
    from app.api.admin import log_analysis
    from app.core.database import get_db_no_commit

    session = _CommitSession()

    async def override_db():
        yield session

    async def fake_upsert(_db: Any, package_name: str, *, updates: dict[str, str | None]):
        assert package_name == "com.example.app"
        assert updates == {"alias": ""}
        return {"package_name": package_name, "alias": "", "company": "Keep", "account": "Keep"}

    app.dependency_overrides[get_db_no_commit] = override_db
    monkeypatch.setattr(log_analysis.log_analysis_service, "upsert_package_profile", fake_upsert)
    try:
        with TestClient(app) as client:
            response = client.put(
                "/api/admin/package-profiles/com.example.app",
                headers=_auth_headers(),
                json={"alias": ""},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["data"]["alias"] == ""
    assert session.committed is True


def test_package_profile_update_rejects_unknown_field():
    from app.admin_main import app

    with TestClient(app) as client:
        response = client.put(
            "/api/admin/package-profiles/com.example.app",
            headers=_auth_headers(),
            json={"unknown": "value"},
        )

    assert response.status_code == 422


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


def test_admin_events_passes_valid_log_level_to_service(monkeypatch):
    from app.admin_main import app
    from app.api.admin import dashboard

    async def fake_get_events(_db: Any, **filters: Any) -> dict[str, Any]:
        assert filters["log_level"] == "info"
        return {"total": 0, "page": 1, "page_size": 20, "items": []}

    monkeypatch.setattr(dashboard.analysis_service, "get_events", fake_get_events)

    with TestClient(app) as client:
        response = client.get("/api/admin/events?log_level=info", headers=_auth_headers())

    assert response.status_code == 200


def test_admin_events_passes_sdk_version_to_service(monkeypatch):
    from app.admin_main import app
    from app.api.admin import dashboard

    async def fake_get_events(_db: Any, **filters: Any) -> dict[str, Any]:
        assert filters["sdk_version"] == "1.4.0"
        return {"total": 0, "page": 1, "page_size": 20, "items": []}

    monkeypatch.setattr(dashboard.analysis_service, "get_events", fake_get_events)

    with TestClient(app) as client:
        response = client.get(
            "/api/admin/events?sdk_version=1.4.0",
            headers=_auth_headers(),
        )

    assert response.status_code == 200


def test_admin_events_passes_complete_hour_range_to_service(monkeypatch):
    from app.admin_main import app
    from app.api.admin import dashboard

    async def fake_get_events(_db: Any, **filters: Any) -> dict[str, Any]:
        assert filters["date_from"] == date(2026, 9, 20)
        assert filters["hour_from"] == 8
        assert filters["date_to"] == date(2026, 9, 22)
        assert filters["hour_to"] == 17
        return {"total": 0, "page": 1, "page_size": 20, "items": []}

    monkeypatch.setattr(dashboard.analysis_service, "get_events", fake_get_events)

    with TestClient(app) as client:
        response = client.get(
            "/api/admin/events",
            params={
                "event_type": "log",
                "date_from": "2026-09-20",
                "hour_from": 8,
                "date_to": "2026-09-22",
                "hour_to": 17,
            },
            headers=_auth_headers(),
        )

    assert response.status_code == 200


@pytest.mark.parametrize(
    "query",
    [
        "date_from=2026-09-20&date_to=2026-09-22&hour_from=8",
        "date_from=2026-09-20&hour_from=8&hour_to=17",
        "date_from=2026-09-20&date_to=2026-09-22&hour_from=-1&hour_to=17",
    ],
)
def test_admin_events_rejects_invalid_hour_ranges(query: str):
    from app.admin_main import app

    with TestClient(app) as client:
        response = client.get(f"/api/admin/events?{query}", headers=_auth_headers())

    assert response.status_code == 422


def test_event_filter_options_returns_payload(monkeypatch):
    from app.admin_main import app
    from app.api.admin import dashboard

    async def fake_options(_db: Any, *, package_name: str | None) -> dict[str, list[str]]:
        assert package_name == "com.example.alpha"
        return {
            "package_names": ["com.example.alpha"],
            "sdk_versions": ["1.2.0"],
        }

    monkeypatch.setattr(dashboard.analysis_service, "get_event_filter_options", fake_options)

    with TestClient(app) as client:
        response = client.get(
            "/api/admin/events/filter-options?package_name=com.example.alpha",
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    assert response.json() == {
        "code": 0,
        "data": {
            "package_names": ["com.example.alpha"],
            "sdk_versions": ["1.2.0"],
        },
    }


def test_admin_events_rejects_invalid_log_level():
    from app.admin_main import app

    with TestClient(app) as client:
        response = client.get("/api/admin/events?log_level=fatal", headers=_auth_headers())

    assert response.status_code == 422


def test_admin_breakdown_defaults_to_utc_plus_8_business_date(monkeypatch):
    from app.admin_main import app
    from app.api.admin import dashboard
    from app.core import timezone as business_timezone

    async def fake_breakdown(_db: Any, target_date: date, dimension: str) -> list[dict[str, Any]]:
        assert target_date == date(2026, 8, 17)
        assert dimension == "event_type"
        return []

    fixed_utc_now = datetime(2026, 8, 16, 18, tzinfo=timezone.utc)
    monkeypatch.setattr(dashboard, "business_today", lambda: business_timezone.business_today(fixed_utc_now))
    monkeypatch.setattr(dashboard.analysis_service, "get_breakdown", fake_breakdown)

    with TestClient(app) as client:
        response = client.get("/api/admin/dashboard/breakdown", headers=_auth_headers())

    assert response.status_code == 200


def test_get_configs_returns_grouped_payload(monkeypatch):
    from app.admin_main import app
    from app.api.admin import config_mgr

    async def fake_list_configs(_db: Any, package_name: str | None = None) -> dict[str, Any]:
        assert package_name is None
        return {
            "published": [{"id": 1, "version": "20260630_v3"}],
            "drafts": [{"id": 2, "version": "draft_001"}],
            "history": [{"id": 3, "version": "20260629_v2", "status": "archived"}],
        }

    monkeypatch.setattr(config_mgr.config_service, "list_configs", fake_list_configs)

    with TestClient(app) as client:
        response = client.get("/api/admin/configs", headers=_auth_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["published"][0]["version"] == "20260630_v3"


def test_create_config_requires_package_name():
    from app.admin_main import app
    with TestClient(app) as client:
        response = client.post(
            "/api/admin/configs",
            headers=_auth_headers(),
            json={"config_data": {"mainConfig": {}, "newTouchConfig": {}, "newTextRuleConfig": {}}},
        )
    assert response.status_code == 422


def test_create_config_passes_normalized_package_name(monkeypatch):
    from app.admin_main import app
    from app.api.admin import config_mgr

    async def fake_create(_db, package_name, config_data, change_log):
        assert package_name == "com.example.app"
        assert set(config_data) == {"mainConfig", "newTouchConfig", "newTextRuleConfig"}
        return {"id": 9, "package_name": package_name}

    monkeypatch.setattr(config_mgr.config_service, "create_config", fake_create)
    with TestClient(app) as client:
        response = client.post(
            "/api/admin/configs",
            headers=_auth_headers(),
            json={
                "package_name": "COM.EXAMPLE.APP",
                "config_data": {"mainConfig": {}, "newTouchConfig": {}, "newTextRuleConfig": {}},
                "change_log": "init",
            },
        )
    assert response.status_code == 200
    assert response.json()["data"]["package_name"] == "com.example.app"


def test_publish_config_returns_publish_result(monkeypatch):
    from app.admin_main import app
    from app.api.admin import config_mgr

    async def fake_publish(_db: Any, config_id: int, published_by: str) -> dict[str, Any]:
        assert config_id == 6
        assert published_by == "32e5c0e2"
        return {
            "version": "20260630_v3",
            "publish_at": "2026-06-30T10:35:00Z",
            "cdn_url": "https://cdn.test.local/config/latest.json",
            "cos_key": "config/v20260630_v3.json",
        }

    monkeypatch.setattr(config_mgr.config_service, "publish_config", fake_publish)

    with TestClient(app) as client:
        response = client.post("/api/admin/configs/6/publish", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json()["data"]["cdn_url"] == "https://cdn.test.local/config/latest.json"


def test_rollback_config_returns_publish_result(monkeypatch):
    from app.admin_main import app
    from app.api.admin import config_mgr

    async def fake_rollback(_db: Any, config_id: int, published_by: str) -> dict[str, Any]:
        assert config_id == 3
        assert published_by == "32e5c0e2"
        return {
            "version": "20260629_v2",
            "publish_at": "2026-06-30T10:40:00Z",
            "cdn_url": "https://cdn.test.local/config/latest.json",
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


def test_version_serializes_created_at_as_utc_plus_8_business_time():
    from app.services import version_service

    version = type(
        "Version",
        (),
        {
            "id": 1,
            "platform": "ios",
            "version_code": 1,
            "version_name": "1.0.0",
            "update_policy": "optional",
            "download_url": None,
            "release_notes": None,
            "min_sdk_version": None,
            "file_size": None,
            "file_hash": None,
            "status": "active",
            "created_at": datetime(2026, 8, 17, 10, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 8, 17, 10, tzinfo=timezone.utc),
        },
    )()

    result = version_service._serialize_version(version)

    assert result["created_at"] == "2026-08-17T18:00:00+08:00"
