from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.core.database import get_db_no_commit


TOKEN = "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0"


def auth_headers(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class Db:
    async def commit(self):
        pass

    async def rollback(self):
        pass


def override_db():
    async def dependency():
        yield Db()

    return dependency


def test_log_analysis_routes_are_registered_and_require_authentication():
    from app.admin_main import app

    paths = {route.path for route in app.routes}
    assert "/api/admin/package-profiles" in paths
    assert "/api/admin/log-analysis/columns" in paths
    with TestClient(app) as client:
        profile = client.get("/api/admin/package-profiles?package_name=com.example.app")
        columns = client.get("/api/admin/log-analysis/columns")
    assert profile.status_code == 401
    assert columns.status_code == 401


def test_profile_get_and_put_use_normalized_package_and_null_safe_response(monkeypatch):
    from app.admin_main import app
    from app.api.admin import log_analysis

    calls: list[tuple[Any, ...]] = []

    async def fake_get(_db, package_name):
        calls.append(("get", package_name))
        return {"package_name": package_name, "alias": "", "company": "", "account": ""}

    async def fake_put(_db, package_name, *, alias, company, account):
        calls.append(("put", package_name, alias, company, account))
        return {"package_name": package_name, "alias": alias, "company": company, "account": account}

    monkeypatch.setattr(log_analysis.log_analysis_service, "get_package_profile", fake_get)
    monkeypatch.setattr(log_analysis.log_analysis_service, "upsert_package_profile", fake_put)
    app.dependency_overrides[get_db_no_commit] = override_db()
    try:
        with TestClient(app) as client:
            get_response = client.get(
                "/api/admin/package-profiles?package_name=COM.EXAMPLE.APP",
                headers=auth_headers(),
            )
            put_response = client.put(
                "/api/admin/package-profiles/COM.EXAMPLE.APP",
                headers=auth_headers(),
                json={"alias": "", "company": "Example", "account": "account-1"},
            )
    finally:
        app.dependency_overrides.clear()

    assert get_response.status_code == 200
    assert get_response.json()["data"]["alias"] == ""
    assert put_response.status_code == 200
    assert calls == [
        ("get", "com.example.app"),
        ("put", "com.example.app", "", "Example", "account-1"),
    ]


def test_profile_rejects_unknown_fields_and_invalid_package_name():
    from app.admin_main import app

    with TestClient(app) as client:
        unknown = client.put(
            "/api/admin/package-profiles/com.example.app",
            headers=auth_headers(),
            json={"alias": "x", "display_name": "forbidden"},
        )
        invalid = client.put(
            "/api/admin/package-profiles/NOT A PACKAGE",
            headers=auth_headers(),
            json={"alias": "x"},
        )
    assert unknown.status_code == 422
    assert invalid.status_code == 422


def test_columns_get_returns_catalog_defaults_and_current(monkeypatch):
    from app.admin_main import app
    from app.api.admin import log_analysis

    expected = {
        "available_columns": ["date", "package_name"],
        "default_columns": ["date", "package_name"],
        "columns": ["package_name", "date"],
    }

    async def fake_get(_db):
        return expected

    monkeypatch.setattr(log_analysis.log_analysis_service, "get_log_analysis_columns", fake_get)
    app.dependency_overrides[get_db_no_commit] = override_db()
    try:
        with TestClient(app) as client:
            response = client.get("/api/admin/log-analysis/columns", headers=auth_headers())
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["data"] == expected


def test_columns_put_preserves_input_order_and_rejects_invalid_payloads(monkeypatch):
    from app.admin_main import app
    from app.api.admin import log_analysis

    calls = []

    async def fake_save(_db, columns):
        calls.append(columns)
        return {"available_columns": columns, "default_columns": columns, "columns": columns}

    monkeypatch.setattr(log_analysis.log_analysis_service, "save_log_analysis_columns", fake_save)
    app.dependency_overrides[get_db_no_commit] = override_db()
    try:
        with TestClient(app) as client:
            valid = client.put(
                "/api/admin/log-analysis/columns",
                headers=auth_headers(),
                json={"columns": ["package_name", "date"]},
            )
            duplicate = client.put(
                "/api/admin/log-analysis/columns",
                headers=auth_headers(),
                json={"columns": ["date", "date", "package_name"]},
            )
            unknown = client.put(
                "/api/admin/log-analysis/columns",
                headers=auth_headers(),
                json={"columns": ["date", "package_name", "owner"]},
            )
            empty = client.put(
                "/api/admin/log-analysis/columns",
                headers=auth_headers(),
                json={"columns": []},
            )
            missing_fixed = client.put(
                "/api/admin/log-analysis/columns",
                headers=auth_headers(),
                json={"columns": ["alias"]},
            )
    finally:
        app.dependency_overrides.clear()

    assert valid.status_code == 200
    assert calls == [["package_name", "date"]]
    assert all(response.status_code == 422 for response in (duplicate, unknown, empty, missing_fixed))


def test_invalid_admin_token_is_rejected():
    from app.admin_main import app

    with TestClient(app) as client:
        response = client.get(
            "/api/admin/log-analysis/columns",
            headers=auth_headers("wrong-token"),
        )
    assert response.status_code == 401


def test_database_error_uses_safe_http_detail(monkeypatch):
    from app.admin_main import app
    from app.api.admin import log_analysis

    async def fail(_db):
        raise RuntimeError("password=secret SQL TOKEN")

    monkeypatch.setattr(log_analysis.log_analysis_service, "get_log_analysis_columns", fail)
    app.dependency_overrides[get_db_no_commit] = override_db()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/api/admin/log-analysis/columns", headers=auth_headers())
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 500
    assert response.json()["detail"] == "列配置查询失败"
    assert "secret" not in response.text
