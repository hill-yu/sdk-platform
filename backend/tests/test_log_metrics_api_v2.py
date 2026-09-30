from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.timezone import business_hour_utc_range


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0"}


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
