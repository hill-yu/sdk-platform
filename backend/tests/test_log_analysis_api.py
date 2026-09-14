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


def test_summary_route_passes_filters_and_rejects_invalid_page_sort(monkeypatch):
    from app.admin_main import app
    from app.api.admin import log_analysis

    calls = []

    async def fake_summary(_db, **kwargs):
        calls.append(kwargs)
        return {"total": 0, "page": kwargs["page"], "page_size": kwargs["page_size"], "items": []}

    monkeypatch.setattr(log_analysis.log_analysis_service, "get_log_analysis_summary", fake_summary)
    app.dependency_overrides[get_db_no_commit] = override_db()
    try:
        with TestClient(app) as client:
            valid = client.get(
                "/api/admin/log-analysis/summary?date_from=2026-08-17&date_to=2026-08-17"
                "&package_name=COM.EXAMPLE.APP&device_id=device-1&page=2&page_size=50"
                "&sort_by=success_rate&sort_order=asc",
                headers=auth_headers(),
            )
            invalid_page_size = client.get(
                "/api/admin/log-analysis/summary?page_size=101",
                headers=auth_headers(),
            )
            invalid_sort = client.get(
                "/api/admin/log-analysis/summary?sort_by=decoded_payload",
                headers=auth_headers(),
            )
    finally:
        app.dependency_overrides.clear()

    assert valid.status_code == 200
    assert calls[0]["package_name"] == "com.example.app"
    assert calls[0]["page"] == 2
    assert calls[0]["sort_by"] == "success_rate"
    assert invalid_page_size.status_code == 422
    assert invalid_sort.status_code == 422


def test_details_route_requires_group_key_and_detail_route_requires_composite_key(monkeypatch):
    from app.admin_main import app
    from app.api.admin import log_analysis

    async def fake_details(_db, **_kwargs):
        return {"total": 1, "page": 1, "page_size": 20, "items": [{"event_id": 7}]}

    async def fake_detail(_db, **_kwargs):
        return {"event_id": 7, "event_server_ts": "2026-08-17T09:02:03+08:00", "record_index": 0, "extra": "H1"}

    monkeypatch.setattr(log_analysis.log_analysis_service, "get_log_analysis_details", fake_details)
    monkeypatch.setattr(log_analysis.log_analysis_service, "get_log_analysis_detail", fake_detail)
    app.dependency_overrides[get_db_no_commit] = override_db()
    try:
        with TestClient(app) as client:
            missing_group = client.get(
                "/api/admin/log-analysis/details",
                headers=auth_headers(),
            )
            details = client.get(
                "/api/admin/log-analysis/details?date=2026-08-17&package_name=COM.EXAMPLE.APP",
                headers=auth_headers(),
            )
            missing_composite = client.get(
                "/api/admin/log-analysis/details/7",
                headers=auth_headers(),
            )
            detail = client.get(
                "/api/admin/log-analysis/details/7?event_server_ts=2026-08-17T01:02:03Z&record_index=0",
                headers=auth_headers(),
            )
    finally:
        app.dependency_overrides.clear()

    assert missing_group.status_code == 422
    assert details.status_code == 200
    assert missing_composite.status_code == 422
    assert detail.status_code == 200
    assert detail.json()["data"]["extra"] == "H1"


def test_reparse_requires_scope_and_returns_pending_job_without_sync_processing(monkeypatch):
    from app.admin_main import app
    from app.api.admin import log_analysis

    calls = []

    async def fake_reparse(_db, **kwargs):
        calls.append(kwargs)
        return {"id": 77, "status": "pending", "package_name": kwargs["package_name"]}

    monkeypatch.setattr(log_analysis.log_analysis_service, "create_reparse_job", fake_reparse)
    app.dependency_overrides[get_db_no_commit] = override_db()
    try:
        with TestClient(app) as client:
            unbounded = client.post(
                "/api/admin/log-analysis/reparse",
                headers=auth_headers(),
                json={},
            )
            valid = client.post(
                "/api/admin/log-analysis/reparse",
                headers=auth_headers(),
                json={"package_name": "COM.EXAMPLE.APP", "status": "failed"},
            )
    finally:
        app.dependency_overrides.clear()

    assert unbounded.status_code == 422
    assert valid.status_code == 200
    assert valid.json()["data"]["status"] == "pending"
    assert calls[0]["package_name"] == "com.example.app"
