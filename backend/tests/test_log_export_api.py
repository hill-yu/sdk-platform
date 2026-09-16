from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient

TOKEN = "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
JOB_ID = UUID("3f21f57d-9a85-4a69-a684-a7ff3ee26bc1")


def test_log_export_routes_require_admin_token():
    from app.admin_main import app
    with TestClient(app) as client:
        assert client.get("/api/admin/log-packages").status_code == 401
        assert client.post("/api/admin/log-exports", json={"package_names": ["com.a"]}).status_code == 401


def test_search_and_create_export(monkeypatch):
    from app.admin_main import app
    from app.api.admin import log_exports

    async def fake_search(_db, keyword, limit):
        assert (keyword, limit) == ("tech", 20)
        return ["com.tech.a", "com.tech.b"]

    async def fake_create(_db, body):
        assert body.package_names == ["com.a", "com.b"]
        assert body.log_level == "info"
        return {"id": str(JOB_ID), "status": "pending"}

    monkeypatch.setattr(log_exports.log_export_service, "search_packages", fake_search)
    monkeypatch.setattr(log_exports.log_export_service, "create_job", fake_create)
    with TestClient(app) as client:
        result = client.get("/api/admin/log-packages?keyword=tech", headers=HEADERS)
        created = client.post("/api/admin/log-exports", headers=HEADERS, json={
            "package_names": ["com.a", "com.b"], "log_level": "info",
        })
    assert result.json()["data"]["items"] == ["com.tech.a", "com.tech.b"]
    assert created.json()["data"]["status"] == "pending"


def test_get_unknown_job_returns_404(monkeypatch):
    from app.admin_main import app
    from app.api.admin import log_exports

    async def fake_get(_db, _job_id):
        return None
    monkeypatch.setattr(log_exports.log_export_service, "get_job", fake_get)
    with TestClient(app) as client:
        response = client.get(f"/api/admin/log-exports/{JOB_ID}", headers=HEADERS)
    assert response.status_code == 404


def test_download_requires_success(monkeypatch):
    from app.admin_main import app
    from app.api.admin import log_exports

    async def fake_get(_db, _job_id):
        return SimpleNamespace(status="running")
    monkeypatch.setattr(log_exports.log_export_service, "get_job", fake_get)
    with TestClient(app) as client:
        response = client.get(f"/api/admin/log-exports/{JOB_ID}/download", headers=HEADERS)
    assert response.status_code == 409


def test_download_successful_csv(monkeypatch, tmp_path):
    from app.admin_main import app
    from app.api.admin import log_exports

    csv_file = tmp_path / f"{JOB_ID}.csv"
    csv_file.write_text("id,extra\n1,raw\n", encoding="utf-8")
    async def fake_get(_db, _job_id):
        return SimpleNamespace(id=JOB_ID, status="success", file_path=str(csv_file))
    monkeypatch.setattr(log_exports.log_export_service, "get_job", fake_get)
    monkeypatch.setattr(log_exports.get_settings(), "LOG_EXPORT_DIR", str(tmp_path))
    with TestClient(app) as client:
        response = client.get(f"/api/admin/log-exports/{JOB_ID}/download", headers=HEADERS)
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "sdk-logs-" in response.headers["content-disposition"]
