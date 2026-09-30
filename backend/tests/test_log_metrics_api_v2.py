from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.timezone import business_hour_utc_range


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0"}


class Db:
    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


def override_db():
    async def dependency():
        yield Db()

    return dependency


def test_parse_job_request_normalizes_package_and_builds_utc8_range() -> None:
    from app.schemas.log_metrics_schemas import LogParseJobCreateRequest

    request = LogParseJobCreateRequest(
        package_name="COM.Example.App",
        date_from=date(2026, 9, 20),
        hour_from=8,
        date_to=date(2026, 9, 22),
        hour_to=17,
    )

    assert request.package_name == "com.example.app"
    assert request.utc_range() == business_hour_utc_range(
        date(2026, 9, 20), 8, date(2026, 9, 22), 17
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"package_name": "com.example.app", "date_from": "2026-09-20", "hour_from": 8, "date_to": "2026-09-20", "hour_to": 7},
        {"package_name": "com.example.app", "date_from": "2026-09-01", "hour_from": 0, "date_to": "2026-09-08", "hour_to": 0},
        {"package_name": "com.example.app", "date_from": "2026-09-20", "hour_from": 8, "date_to": "2026-09-22", "hour_to": 17, "unexpected": True},
    ],
)
def test_parse_job_request_rejects_invalid_scope(payload: dict[str, object]) -> None:
    from app.schemas.log_metrics_schemas import LogParseJobCreateRequest

    with pytest.raises(ValidationError):
        LogParseJobCreateRequest.model_validate(payload)


def test_parse_job_routes_are_registered_and_require_admin_authentication() -> None:
    from app.admin_main import app

    paths = {route.path for route in app.routes}
    assert "/api/admin/log-analysis/parse-jobs" in paths
    assert "/api/admin/log-analysis/parse-jobs/{job_id}" in paths
    assert "/api/admin/log-analysis/parse-jobs/{job_id}/cancel" in paths
    assert "/api/admin/log-analysis/coverage" in paths

    with TestClient(app) as client:
        response = client.post("/api/admin/log-analysis/parse-jobs", json={})

    assert response.status_code == 401


def test_create_parse_job_route_passes_utc_scope_and_returns_envelope(monkeypatch) -> None:
    from app.admin_main import app
    from app.api.admin import log_metrics

    calls = []

    async def fake_create(_db, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(id=91)

    monkeypatch.setattr(log_metrics._service(), "create_parse_job", fake_create)
    monkeypatch.setattr(log_metrics._service(), "serialize_parse_job", lambda job: {"id": job.id})
    app.dependency_overrides.clear()
    app.dependency_overrides[log_metrics.get_db_no_commit] = override_db()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/admin/log-analysis/parse-jobs",
                headers=auth_headers(),
                json={
                    "package_name": "COM.EXAMPLE.APP",
                    "date_from": "2026-09-20",
                    "hour_from": 8,
                    "date_to": "2026-09-20",
                    "hour_to": 17,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["data"] == {"id": 91}
    assert calls[0]["package_name"] == "com.example.app"
    assert calls[0]["range_start"].isoformat() == "2026-09-20T00:00:00+00:00"
    assert calls[0]["range_end"].isoformat() == "2026-09-20T10:00:00+00:00"


def test_create_parse_job_route_returns_conflict_for_active_job(monkeypatch) -> None:
    from app.admin_main import app
    from app.api.admin import log_metrics

    async def fake_create(_db, **kwargs):
        raise log_metrics._service().ActiveParseJobError("已有解析任务正在执行")

    monkeypatch.setattr(log_metrics._service(), "create_parse_job", fake_create)
    app.dependency_overrides.clear()
    app.dependency_overrides[log_metrics.get_db_no_commit] = override_db()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/admin/log-analysis/parse-jobs",
                headers=auth_headers(),
                json={
                    "package_name": "com.example.app",
                    "date_from": "2026-09-20",
                    "hour_from": 8,
                    "date_to": "2026-09-20",
                    "hour_to": 17,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
