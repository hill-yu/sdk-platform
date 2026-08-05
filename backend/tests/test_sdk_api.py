from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.core.config import get_settings
from app.core.database import get_db, get_db_no_commit

from tests.conftest import (
    StubReadSession,
    StubWriteSession,
    override_read_db,
    override_write_db,
)


def test_version_returns_no_available_version_when_table_is_empty(client):
    client.app.dependency_overrides[get_db_no_commit] = override_read_db(StubReadSession(None))

    response = client.get("/api/v1/version", params={"platform": "ios", "current_version": 0})

    assert response.status_code == 200
    assert response.json() == {
        "code": 0,
        "data": {
            "has_update": False,
            "current_version": 0,
            "message": "暂无可用版本",
        },
    }


def test_version_returns_requested_current_version_when_already_latest(client):
    latest = SimpleNamespace(
        platform="ios",
        version_code=120,
        version_name="1.2.0",
        update_policy="suggest",
        download_url="https://cdn.test.local/sdk/ios/1.2.0.zip",
        release_notes="ok",
        file_size=1,
        file_hash="sha256:test",
        min_sdk_version=100,
    )
    client.app.dependency_overrides[get_db_no_commit] = override_read_db(StubReadSession(latest))

    response = client.get("/api/v1/version", params={"platform": "ios", "current_version": 130})

    assert response.status_code == 200
    assert response.json() == {
        "code": 0,
        "data": {
            "has_update": False,
            "current_version": 130,
            "message": "已是最新版本",
        },
    }


def test_config_meta_returns_304_when_etag_matches_published_version(client):
    published = SimpleNamespace(
        version="20260630_v3",
        publish_at=datetime(2026, 6, 30, 10, 0, tzinfo=timezone.utc),
        cdn_url="https://cdn.test.local/config/latest.json",
    )
    client.app.dependency_overrides[get_db_no_commit] = override_read_db(StubReadSession(published))

    response = client.get(
        "/api/v1/config/meta",
        params={"app_id": "demo", "config_version": "20260630_v2"},
        headers={"If-None-Match": '"20260630_v3"'},
    )

    assert response.status_code == 304
    assert response.headers["etag"] == '"20260630_v3"'


def test_config_meta_returns_environment_configured_metadata_without_required_params(client, monkeypatch):
    monkeypatch.setenv("CONFIG_DELIVERY_MODE", "cos")
    monkeypatch.setenv("CONFIG_META_IS_OPEN", "true")
    monkeypatch.setenv("CONFIG_META_IS_NEWS_TOUCH", "true")
    monkeypatch.setenv("CONFIG_META_IS_NEW_TEXT_RULE", "true")
    monkeypatch.setenv("CONFIG_META_CDN_URL", "https://cdnversion.deeppopgame.xyz/config/latest.json")
    monkeypatch.setenv("CONFIG_META_CDN_URL2", "https://cdnNewtouch.deeppopgame.xyz/config/latest.json")
    monkeypatch.setenv("CONFIG_META_CDN_URL3", "https://cdnNewTextRule.deeppopgame.xyz/config/latest.json")
    get_settings.cache_clear()
    published = SimpleNamespace(
        version="1.0.11",
        publish_at=datetime(2026, 6, 30, 10, 0, tzinfo=timezone.utc),
        cdn_url="https://cdn.test.local/config/latest.json",
    )
    client.app.dependency_overrides[get_db_no_commit] = override_read_db(StubReadSession(published))

    response = client.get("/api/v1/config/meta")

    assert response.status_code == 200
    assert response.json() == {
        "code": 0,
        "data": {
            "version": "1.0.11",
            "updated_at": "2026-06-30T10:00:00+00:00",
            "isOpen": True,
            "isNewsTouch": True,
            "isNewTextRule": True,
            "cdn_url": "https://cdnversion.deeppopgame.xyz/config/latest.json",
            "cdn_url2": "https://cdnNewtouch.deeppopgame.xyz/config/latest.json",
            "cdn_url3": "https://cdnNewTextRule.deeppopgame.xyz/config/latest.json",
        },
    }
    get_settings.cache_clear()


def test_config_latest_returns_published_config_json(client):
    published = SimpleNamespace(
        version="1.0.11",
        publish_at=datetime(2026, 6, 30, 10, 0, tzinfo=timezone.utc),
        cdn_url="https://sdk.deeppopgame.xyz/api/v1/config/latest",
        config_data={"features": {"demo": True}},
    )
    client.app.dependency_overrides[get_db_no_commit] = override_read_db(StubReadSession(published))

    response = client.get("/api/v1/config/latest")

    assert response.status_code == 200
    assert response.json() == {
        "version": "1.0.11",
        "updated_at": "2026-06-30T10:00:00+00:00",
        "config": {"features": {"demo": True}},
    }


def test_config_meta_returns_local_urls_in_local_delivery_mode(client, monkeypatch):
    monkeypatch.setenv("CONFIG_DELIVERY_MODE", "local")
    monkeypatch.setenv("CONFIG_META_LOCAL_BASE_URL", "https://sdk.deeppopgame.xyz")
    get_settings.cache_clear()
    published = SimpleNamespace(
        version="1.0.11",
        publish_at=datetime(2026, 6, 30, 10, 0, tzinfo=timezone.utc),
        cdn_url="https://sdk.deeppopgame.xyz/api/v1/config/latest",
    )
    client.app.dependency_overrides[get_db_no_commit] = override_read_db(StubReadSession(published))

    response = client.get("/api/v1/config/meta")

    assert response.status_code == 200
    assert response.json()["data"]["cdn_url"] == "https://sdk.deeppopgame.xyz/api/v1/config/latest"
    assert response.json()["data"]["cdn_url2"] == "https://sdk.deeppopgame.xyz/api/v1/config/latest?type=new_touch"
    assert response.json()["data"]["cdn_url3"] == "https://sdk.deeppopgame.xyz/api/v1/config/latest?type=new_text_rule"
    get_settings.cache_clear()


def test_click_returns_partial_success_when_some_events_are_rejected(client):
    # Use a non-failing session; rejection happens at validation (no element + no page)
    session = StubWriteSession()
    client.app.dependency_overrides[get_db] = override_write_db(session)

    response = client.post(
        "/api/v1/click",
        json={
            "app_id": "demo",
            "device_id": "device-1",
            "events": [
                {"type": "click", "page": "home", "element": "ok_button"},
                {"type": "click"},  # No element, no page → fails validation
            ],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "code": 0,
        "message": "partial_success",
        "data": {"accepted": 1, "rejected": 1},
    }
    # Batch insert was executed (response confirms 1 accepted)
    assert len(session.executed) >= 1


def test_log_returns_422_for_invalid_level(client):
    session = StubWriteSession()
    client.app.dependency_overrides[get_db] = override_write_db(session)

    response = client.post(
        "/api/v1/log",
        json={
            "app_id": "demo",
            "device_id": "device-1",
            "logs": [{"level": "fatal", "message": "bad level"}],
        },
    )

    assert response.status_code == 422


def test_log_returns_ok_when_all_logs_are_accepted(client):
    session = StubWriteSession()
    client.app.dependency_overrides[get_db] = override_write_db(session)

    response = client.post(
        "/api/v1/log",
        headers={"User-Agent": "sdk-test-agent"},
        json={
            "app_id": "demo",
            "device_id": "device-1",
            "logs": [{"level": "info", "message": "hello"}],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "code": 0,
        "message": "ok",
        "data": {"accepted": 1, "rejected": 0},
    }
    # Batch insert was executed successfully (response confirms 1 accepted)
    assert len(session.executed) >= 1
