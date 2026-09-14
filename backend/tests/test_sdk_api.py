from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.core.config import get_settings
from app.core.database import get_db, get_db_no_commit
from app.services.config_crypto import decrypt_payload, encrypt_payload
from app.core.rate_limit import write_limiter
from tests.conftest import StubReadSession, StubWriteSession, override_read_db, override_write_db

TOKEN = "sdk-config-test-token-1234567890"


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _ReturningWriteSession(StubWriteSession):
    def __init__(self):
        super().__init__()
        self.event_statement = None
        self.pending_statement = None

    async def execute(self, statement, *args, **kwargs):
        from sqlalchemy.sql import Insert

        if isinstance(statement, Insert):
            table_name = statement.table.name
            self.executed.append(statement)
            if table_name == "sdk_events":
                self.event_statement = statement
                return _Rows([(501, datetime(2026, 8, 17, 1, 2, 3, tzinfo=timezone.utc))])
            if table_name == "sdk_log_decodes":
                self.pending_statement = statement
                return _Rows([])
        values = getattr(statement, "values_payload", None)
        if values is not None:
            self.executed.append(statement)
            if values and values[0].get("event_type") == "log":
                self.event_statement = statement
                return _Rows([(501, datetime(2026, 8, 17, 1, 2, 3, tzinfo=timezone.utc))])
            self.pending_statement = statement
            return _Rows([])
        return await super().execute(statement, *args, **kwargs)


@pytest.fixture(autouse=True)
def reset_write_limiter():
    write_limiter._store.clear()
    yield
    write_limiter._store.clear()


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
    assert data["updated_at"].endswith("+08:00")
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
    response = client.post(
        "/api/v1/config/packages/com.example.app/versions/1.0.11/new-touch",
        headers=_headers(),
    )
    assert response.status_code == 200
    envelope = response.json()
    assert "config" not in envelope
    assert envelope["config_type"] == "new_touch"
    assert decrypt_payload(envelope, TOKEN) == {"name": "touch"}


def test_package_payload_requires_token(client):
    response = client.post("/api/v1/config/packages/com.example.app/versions/1.0.11/main")
    assert response.status_code == 401


def test_package_payload_get_method_is_disabled(client):
    response = client.get(
        "/api/v1/config/packages/com.example.app/versions/1.0.11/main",
        headers=_headers(),
    )
    assert response.status_code == 405


def test_old_latest_route_is_removed(client):
    assert client.post("/api/v1/config/latest", headers=_headers()).status_code == 404


def test_click_returns_partial_success_when_some_events_are_rejected(client):
    session = StubWriteSession()
    client.app.dependency_overrides[get_db] = override_write_db(session)
    response = client.post("/api/v1/click", json={"package_name": "demo", "device_id": "device-1", "events": [{"type": "click", "page": "home", "element": "ok_button"}, {"type": "click"}]})
    assert response.status_code == 200
    assert response.json()["data"] == {"accepted": 1, "rejected": 1}


def test_click_uses_normalized_package_name(client, monkeypatch):
    from app.api.sdk import click as click_api
    captured = {}

    class Insert:
        def values(self, values):
            captured["values"] = values
            return self

    monkeypatch.setattr(click_api, "pg_insert", lambda _model: Insert())
    client.app.dependency_overrides[get_db] = override_write_db(StubWriteSession())
    response = client.post("/api/v1/click", json={"package_name": " COM.Example.App ", "device_id": "device-1", "events": [{"type": "click", "page": "home"}]})
    assert response.status_code == 200
    assert captured["values"][0]["package_name"] == "com.example.app"


def test_click_rejects_legacy_app_id(client):
    response = client.post("/api/v1/click", json={"app_id": "demo", "device_id": "device-1", "events": [{"type": "click", "page": "home"}]})
    assert response.status_code == 422


def test_log_returns_422_for_invalid_level(client):
    response = client.post("/api/v1/log", json={"package_name": "demo", "device_id": "device-1", "logs": [{"level": "fatal", "extra": "bad"}]})
    assert response.status_code == 422


@pytest.mark.parametrize("extra", [{"key": "value"}, ["value"], 1, True, None])
def test_log_requires_string_extra(client, extra):
    response = client.post("/api/v1/log", json={"package_name": "com.example.app", "device_id": "device-1", "logs": [{"level": "info", "extra": extra}]})
    assert response.status_code == 422


@pytest.mark.parametrize("log_fields", [{}, {"message": None}, {"message": ""}])
def test_log_accepts_empty_message_and_preserves_raw_extra(client, monkeypatch, log_fields):
    from app.api.sdk import log as log_api
    captured = {}

    class Insert:
        def values(self, values):
            self.values_payload = values
            if values and values[0].get("event_type") == "log":
                captured["values"] = values
            return self

        def returning(self, *_columns):
            return self

    monkeypatch.setattr(log_api, "pg_insert", lambda _model: Insert())
    client.app.dependency_overrides[get_db] = override_write_db(_ReturningWriteSession())
    log_entry = {"level": "INFO", "extra": "{ouoghaougoagahdgjalglauoi|dlaugouojlJ}", **log_fields}
    response = client.post("/api/v1/log", json={"package_name": " COM.Example.App ", "device_id": "device-1", "logs": [log_entry]})
    assert response.status_code == 200
    value = captured["values"][0]
    assert value["package_name"] == "com.example.app"
    assert value["payload"]["level"] == "info"
    assert value["payload"]["message"] == ""
    assert value["payload"]["extra"] == "{ouoghaougoagahdgjalglauoi|dlaugouojlJ}"


def test_log_accepts_target_payload_without_device_id(client, monkeypatch):
    from app.api.sdk import log as log_api
    captured = {}

    class Insert:
        def values(self, values):
            self.values_payload = values
            if values and values[0].get("event_type") == "log":
                captured["values"] = values
            return self

        def returning(self, *_columns):
            return self

    monkeypatch.setattr(log_api, "pg_insert", lambda _model: Insert())
    client.app.dependency_overrides[get_db] = override_write_db(_ReturningWriteSession())
    response = client.post(
        "/api/v1/log",
        json={
            "package_name": "com.example.app",
            "logs": [{"level": "info", "message": "", "extra": "raw"}],
        },
    )
    assert response.status_code == 200
    assert captured["values"][0]["device_id"] is None


@pytest.mark.parametrize("missing_field", ["level", "extra"])
def test_log_requires_level_and_extra(client, missing_field):
    log_entry = {"level": "info", "extra": "raw"}
    del log_entry[missing_field]
    response = client.post("/api/v1/log", json={"package_name": "com.example.app", "device_id": "device-1", "logs": [log_entry]})
    assert response.status_code == 422


def test_log_rejects_legacy_app_id(client):
    response = client.post("/api/v1/log", json={"app_id": "demo", "device_id": "device-1", "logs": [{"level": "info", "extra": "raw"}]})
    assert response.status_code == 422


def test_log_returns_quickly_after_returning_insert_and_creates_pending(client, monkeypatch):
    from app.api.sdk import log as log_api
    from sqlalchemy.dialects import postgresql

    def fail_if_decoded(_extra):
        raise AssertionError("decode_extra must not run in the request")

    monkeypatch.setattr(log_api, "decode_extra", fail_if_decoded, raising=False)
    session = _ReturningWriteSession()
    client.app.dependency_overrides[get_db] = override_write_db(session)

    response = client.post(
        "/api/v1/log",
        json={
            "package_name": "com.example.app",
            "device_id": "device-1",
            "logs": [{"level": "info", "extra": "H1|i=GC"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"accepted": 1, "rejected": 0}
    assert session.event_statement is not None
    returning = [column.name for column in session.event_statement._returning]
    assert returning == ["id", "server_ts"]
    assert session.pending_statement is not None
    params = session.pending_statement.compile(dialect=postgresql.dialect()).params
    pending = {
        key.removesuffix("_m0"): value
        for key, value in params.items()
        if key.endswith("_m0")
    }
    assert pending["event_id"] == 501
    assert pending["record_index"] == -1
    assert pending["status"] == "pending"
    assert pending["package_name"] == "com.example.app"
    assert pending["device_id"] == "device-1"
    assert pending["decoder_version"] == "1.0.0"
