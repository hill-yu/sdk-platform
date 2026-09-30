from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.database import get_db_no_commit


TOKEN = "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0"


class Db:
    pass


async def override_db():
    yield Db()


def test_metrics_routes_forward_complete_scope_and_require_admin(monkeypatch):
    from app.admin_main import app
    from app.api.admin import log_metrics

    calls = []

    async def fake_query(_db, **kwargs):
        calls.append(kwargs)
        return {"ok": True}

    for name in ("get_overview", "get_config_breakdown", "get_target_breakdown", "get_failure_breakdown", "get_h1_details"):
        monkeypatch.setattr(log_metrics._metrics_service(), name, fake_query)

    app.dependency_overrides[get_db_no_commit] = override_db
    try:
        with TestClient(app) as client:
            unauthorized = client.get("/api/admin/log-analysis/metrics/overview")
            response = client.get(
                "/api/admin/log-analysis/metrics/overview",
                params={
                    "package_name": "COM.EXAMPLE.APP",
                    "date_from": "2026-09-29",
                    "hour_from": 8,
                    "date_to": "2026-09-29",
                    "hour_to": 17,
                },
                headers={"Authorization": f"Bearer {TOKEN}"},
            )
    finally:
        app.dependency_overrides.clear()

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    assert calls[0]["package_name"] == "com.example.app"
    assert calls[0]["range_start"].isoformat() == "2026-09-29T00:00:00+00:00"
    assert calls[0]["range_end"].isoformat() == "2026-09-29T10:00:00+00:00"
