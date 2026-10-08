from fastapi.testclient import TestClient
import pytest

from app.core.database import get_db_no_commit


TOKEN = "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0"


class Db:
    pass


async def override_db():
    yield Db()


def headers():
    return {"Authorization": f"Bearer {TOKEN}"}


def test_usage_duration_admin_route_requires_token():
    from app.admin_main import app

    with TestClient(app) as client:
        response = client.get("/api/admin/usage-durations")
    assert response.status_code == 401


def test_usage_duration_admin_route_normalizes_package_and_forwards_filters(monkeypatch):
    from app.admin_main import app
    from app.api.admin import usage_duration

    calls = []

    async def fake_query(_db, **kwargs):
        calls.append(kwargs)
        return {
            "summary": {"total_duration_s": 0, "report_count": 0, "device_count": 0},
            "total": 0,
            "page": kwargs["page"],
            "page_size": kwargs["page_size"],
            "items": [],
        }

    monkeypatch.setattr(usage_duration.usage_duration_service, "get_usage_durations", fake_query)
    app.dependency_overrides[get_db_no_commit] = override_db
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/admin/usage-durations",
                params={
                    "package_name": " COM.Example.App ",
                    "device_id": "device-1",
                    "sdk_version": "1.0.3",
                    "ver": "1.0",
                    "date_from": "2026-09-01",
                    "date_to": "2026-09-29",
                    "page": 2,
                    "page_size": 50,
                },
                headers=headers(),
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert calls[0]["package_name"] == "com.example.app"
    assert calls[0]["device_id"] == "device-1"
    assert calls[0]["sdk_version"] == "1.0.3"
    assert calls[0]["ver"] == "1.0"
    assert calls[0]["page"] == 2
    assert calls[0]["page_size"] == 50


def test_usage_duration_admin_rejects_unpaired_and_overlong_dates():
    from app.admin_main import app

    with TestClient(app) as client:
        unpaired = client.get(
            "/api/admin/usage-durations?date_from=2026-09-01",
            headers=headers(),
        )
        overlong = client.get(
            "/api/admin/usage-durations?date_from=2026-08-01&date_to=2026-09-01",
            headers=headers(),
        )
    assert unpaired.status_code == 422
    assert overlong.status_code == 422


def test_usage_duration_admin_rejects_invalid_package_name():
    from app.admin_main import app

    with TestClient(app) as client:
        response = client.get(
            "/api/admin/usage-durations?package_name=!!!",
            headers=headers(),
        )
    assert response.status_code == 422


@pytest.mark.parametrize("field", ["package_name", "device_id", "sdk_version", "ver"])
def test_usage_duration_admin_rejects_empty_filter_values(monkeypatch, field):
    from app.admin_main import app
    from app.api.admin import usage_duration

    async def fake_query(_db, **_kwargs):
        return {
            "summary": {"total_duration_s": 0, "report_count": 0, "device_count": 0},
            "total": 0,
            "page": 1,
            "page_size": 20,
            "items": [],
        }

    monkeypatch.setattr(usage_duration.usage_duration_service, "get_usage_durations", fake_query)
    app.dependency_overrides[get_db_no_commit] = override_db
    with TestClient(app) as client:
        response = client.get(
            "/api/admin/usage-durations",
            params={field: ""},
            headers=headers(),
        )
    app.dependency_overrides.clear()
    assert response.status_code == 422


def test_usage_duration_summary_and_devices_routes_forward_scope(monkeypatch):
    from app.admin_main import app
    from app.api.admin import usage_duration

    calls = []

    async def fake_summary(_db, **kwargs):
        calls.append(("summary", kwargs))
        return {"total": 0, "page": kwargs["page"], "page_size": kwargs["page_size"], "items": []}

    async def fake_devices(_db, **kwargs):
        calls.append(("devices", kwargs))
        return {"total": 0, "page": kwargs["page"], "page_size": kwargs["page_size"], "items": []}

    monkeypatch.setattr(usage_duration.usage_duration_service, "get_usage_summary", fake_summary)
    monkeypatch.setattr(usage_duration.usage_duration_service, "get_usage_devices", fake_devices)
    app.dependency_overrides[get_db_no_commit] = override_db
    try:
        with TestClient(app) as client:
            summary = client.get(
                "/api/admin/usage-durations/summary",
                params={
                    "package_name": "COM.EXAMPLE.APP",
                    "date_from": "2026-09-29",
                    "hour_from": 8,
                    "date_to": "2026-09-29",
                    "hour_to": 17,
                    "page": 2,
                    "page_size": 50,
                },
                headers=headers(),
            )
            devices = client.get(
                "/api/admin/usage-durations/devices",
                params={
                    "package_name": "COM.EXAMPLE.APP",
                    "date_from": "2026-09-29",
                    "date_to": "2026-09-29",
                },
                headers=headers(),
            )
    finally:
        app.dependency_overrides.clear()

    assert summary.status_code == 200
    assert devices.status_code == 200
    assert calls[0][1]["package_name"] == "com.example.app"
    assert calls[0][1]["page"] == 2
    assert calls[1][1]["device_model"] is None
