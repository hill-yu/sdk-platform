from datetime import datetime, timezone
from types import SimpleNamespace

from app.core.config import get_settings
from app.core.database import get_db, get_db_no_commit
from app.services.config_crypto import decrypt_payload, encrypt_payload
from tests.conftest import StubReadSession, StubWriteSession, override_read_db, override_write_db

TOKEN = "sdk-config-test-token-1234567890"


def _headers(token: str = TOKEN):
    return {"Authorization": f"Bearer {token}"}


def _published(package_name="com.example.app", version="1.0.11"):
    data = {"mainConfig": {"name": "main"}, "newTouchConfig": {"name": "touch"}, "newTextRuleConfig": {"name": "text"}}
    return SimpleNamespace(
        package_name=package_name,
        version=version,
        publish_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
        encrypted_config=encrypt_payload(data, package_name, version, "full", TOKEN),
        cos_upload_status="success",
    )


def test_version_returns_no_available_version_when_table_is_empty(client):
    client.app.dependency_overrides[get_db_no_commit] = override_read_db(StubReadSession(None))
    response = client.get("/api/v1/version", params={"platform": "ios", "current_version": 0})
    assert response.status_code == 200
    assert response.json()["data"]["has_update"] is False


def test_meta_requires_package_name(client):
    assert client.post("/api/v1/config/meta", headers=_headers()).status_code == 422


def test_meta_requires_token_before_package_lookup(client):
    assert client.post("/api/v1/config/meta", json={"package_name": "com.example.app"}).status_code == 401


def test_meta_returns_package_version_and_dedicated_urls(client, monkeypatch):
    monkeypatch.setenv("CONFIG_DELIVERY_MODE", "local")
    monkeypatch.setenv("CONFIG_META_LOCAL_BASE_URL", "https://sdk.example.test")
    get_settings.cache_clear()
    published = _published()
    client.app.dependency_overrides[get_db_no_commit] = override_read_db(StubReadSession(published))
    response = client.post("/api/v1/config/meta", headers=_headers(), json={"package_name": "COM.EXAMPLE.APP"})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["package_name"] == "com.example.app"
    assert data["version"] == "1.0.11"
    assert data["cdn_url"].endswith("/com.example.app/versions/1.0.11/main")
    assert data["cdn_url2"].endswith("/com.example.app/versions/1.0.11/new-touch")
    assert data["cdn_url3"].endswith("/com.example.app/versions/1.0.11/new-text-rule")
    get_settings.cache_clear()


def test_meta_returns_404_for_unknown_package(client):
    client.app.dependency_overrides[get_db_no_commit] = override_read_db(StubReadSession(None))
    response = client.post("/api/v1/config/meta", headers=_headers(), json={"package_name": "com.unknown.app"})
    assert response.status_code == 404


def test_package_payload_is_encrypted_and_bound_to_type(client):
    published = _published()
    client.app.dependency_overrides[get_db_no_commit] = override_read_db(StubReadSession(published))
    response = client.get(
        "/api/v1/config/packages/com.example.app/versions/1.0.11/new-touch",
        headers=_headers(),
    )
    assert response.status_code == 200
    envelope = response.json()
    assert "config" not in envelope
    assert envelope["config_type"] == "new_touch"
    assert decrypt_payload(envelope, TOKEN) == {"name": "touch"}


def test_package_payload_requires_token(client):
    response = client.get("/api/v1/config/packages/com.example.app/versions/1.0.11/main")
    assert response.status_code == 401


def test_old_latest_route_is_removed(client):
    assert client.post("/api/v1/config/latest", headers=_headers()).status_code == 404


def test_click_returns_partial_success_when_some_events_are_rejected(client):
    session = StubWriteSession()
    client.app.dependency_overrides[get_db] = override_write_db(session)
    response = client.post("/api/v1/click", json={"app_id": "demo", "device_id": "device-1", "events": [{"type": "click", "page": "home", "element": "ok_button"}, {"type": "click"}]})
    assert response.status_code == 200
    assert response.json()["data"] == {"accepted": 1, "rejected": 1}


def test_log_returns_422_for_invalid_level(client):
    session = StubWriteSession()
    client.app.dependency_overrides[get_db] = override_write_db(session)
    response = client.post("/api/v1/log", json={"app_id": "demo", "device_id": "device-1", "logs": [{"level": "fatal", "message": "bad"}]})
    assert response.status_code == 422
