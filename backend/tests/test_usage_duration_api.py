import pytest

from app.core.database import get_db
from app.core.rate_limit import write_limiter
from tests.conftest import StubWriteSession, override_write_db


VALID_BODY = {
    "package_name": " COM.Example.App ",
    "device_id": "device-001",
    "device_model": "iPhone13,2",
    "os": "17.5.1",
    "ver": "1.0",
    "sdk_version": "1.0.3",
    "duration_s": 60,
}


@pytest.fixture(autouse=True)
def reset_limiter():
    write_limiter._store.clear()
    yield
    write_limiter._store.clear()


def test_usage_duration_writes_normalized_record_and_returns_acceptance(client):
    session = StubWriteSession()
    client.app.dependency_overrides[get_db] = override_write_db(session)
    response = client.post(
        "/api/v1/usage-duration",
        json=VALID_BODY,
        headers={"User-Agent": "ExampleSDK/1.0.3"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "code": 0,
        "message": "ok",
        "data": {"accepted": 1, "rejected": 0},
    }
    assert len(session.records) == 1
    record = session.records[0]
    assert record.package_name == "com.example.app"
    assert record.device_id == "device-001"
    assert record.device_model == "iPhone13,2"
    assert record.os == "17.5.1"
    assert record.app_version == "1.0"
    assert record.sdk_version == "1.0.3"
    assert record.duration_s == 60
    assert str(record.ip) == "testclient"
    assert record.user_agent == "ExampleSDK/1.0.3"
    assert record.server_ts.tzinfo is not None


@pytest.mark.parametrize("duration_s", [1, 3600])
def test_usage_duration_accepts_inclusive_boundaries(client, duration_s):
    session = StubWriteSession()
    client.app.dependency_overrides[get_db] = override_write_db(session)
    response = client.post(
        "/api/v1/usage-duration",
        json={**VALID_BODY, "duration_s": duration_s},
    )
    assert response.status_code == 200


@pytest.mark.parametrize("duration_s", [0, -1, 3601, 1.5, "60"])
def test_usage_duration_rejects_invalid_or_non_integer_duration(client, duration_s):
    response = client.post(
        "/api/v1/usage-duration",
        json={**VALID_BODY, "duration_s": duration_s},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "field",
    ["package_name", "device_id", "device_model", "os", "ver", "sdk_version", "duration_s"],
)
def test_usage_duration_requires_all_contract_fields(client, field):
    body = dict(VALID_BODY)
    del body[field]
    assert client.post("/api/v1/usage-duration", json=body).status_code == 422


def test_usage_duration_uses_write_limiter(client):
    session = StubWriteSession()
    client.app.dependency_overrides[get_db] = override_write_db(session)
    responses = [
        client.post("/api/v1/usage-duration", json=VALID_BODY)
        for _ in range(write_limiter.max + 1)
    ]
    assert responses[-1].status_code == 429


def test_usage_duration_returns_safe_500_on_database_error(client):
    session = StubWriteSession(fail_predicate=lambda _record: True)
    client.app.dependency_overrides[get_db] = override_write_db(session)
    response = client.post("/api/v1/usage-duration", json=VALID_BODY)
    assert response.status_code == 500
    assert response.json()["detail"] == "数据库写入失败"
