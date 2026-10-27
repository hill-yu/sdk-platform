from __future__ import annotations

import asyncio
import base64
import hashlib
from typing import get_type_hints

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin.auth import router as auth_router
import app.api.admin.auth as auth_module
from app.api.admin.deps import require_admin_token, session_cookie_name, session_store
from app.core.config import get_settings
from app.services.admin_auth_service import (
    AdminAuthConfigError,
    AdminAuthService,
    FailureRateLimiter,
    SessionStore,
    parse_password_hash,
)


def _hash(password: str) -> str:
    salt = b"0123456789abcdef"
    digest = hashlib.scrypt(password.encode(), salt=salt, n=32768, r=8, p=1, dklen=32, maxmem=67108864)
    enc = lambda value: base64.urlsafe_b64encode(value).decode().rstrip("=")
    return f"scrypt$N=32768,r=8,p=1${enc(salt)}${enc(digest)}"


def test_parse_password_hash_rejects_non_approved_parameters() -> None:
    with pytest.raises(AdminAuthConfigError):
        parse_password_hash(_hash("secret").replace("N=32768", "N=65536"))


def test_password_verification_is_uniform_for_unknown_user() -> None:
    service = AdminAuthService("admin", _hash("secret"))
    assert asyncio.run(service.verify("admin", "secret")) is True
    assert asyncio.run(service.verify("nobody", "secret")) is False
    assert asyncio.run(service.verify("admin", "wrong")) is False


def test_session_store_revokes_and_expires_sessions() -> None:
    store = SessionStore(max_sessions=1)
    session = store.create("admin", ttl_seconds=60, now=100.0)
    assert store.get(session.session_id, now=101.0).username == "admin"
    store.revoke(session.session_id)
    assert store.get(session.session_id, now=101.0) is None
    assert all(session.session_id not in repr(value) for value in store._sessions.values())
    store.create("admin", ttl_seconds=60, now=100.0)
    with pytest.raises(RuntimeError):
        store.create("admin", ttl_seconds=60, now=100.0)


def test_session_store_get_annotation_never_exposes_raw_session_type() -> None:
    assert "StoredSession" in str(get_type_hints(SessionStore.get)["return"])


def test_failure_limiter_purges_expired_keys() -> None:
    limiter = FailureRateLimiter(max_failures=2, window_seconds=10, max_keys=2)
    assert limiter.record_failure("one", now=0) == 1
    assert limiter.record_failure("one", now=1) == 2
    assert limiter.retry_after("one", now=11) == 0
    assert limiter.record_failure("two", now=11) == 1


def test_unicode_username_is_a_normalized_failed_login() -> None:
    service = AdminAuthService("admin", _hash("secret"))
    assert asyncio.run(service.verify("管理员", "secret")) is False


@pytest.fixture()
def auth_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ADMIN_TOKEN", "legacy-token-" + "x" * 32)
    monkeypatch.setenv("ADMIN_PASSWORD_LOGIN_ENABLED", "true")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", _hash("correct horse"))
    monkeypatch.setenv("ADMIN_SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("ADMIN_AUTH_ALLOWED_ORIGINS", "http://localhost:5173")
    get_settings.cache_clear()
    auth_module._limiter._failures.clear()
    auth_module._ip_limiter._failures.clear()
    test_app = FastAPI()
    test_app.include_router(auth_router, prefix="/api/admin")

    @test_app.get("/protected", dependencies=[Depends(require_admin_token)])
    async def protected():
        return {"ok": True}

    @test_app.post("/protected", dependencies=[Depends(require_admin_token)])
    async def protected_write():
        return {"ok": True}

    @test_app.middleware("http")
    async def no_store_auth_responses(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/admin/auth/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    origins = ["http://localhost:5173"]
    test_app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    with TestClient(test_app) as client:
        yield client
    get_settings.cache_clear()
    auth_module._limiter._failures.clear()
    auth_module._ip_limiter._failures.clear()


def test_wrong_credentials_are_uniform_and_not_cached(auth_client: TestClient) -> None:
    headers = {"Origin": "http://localhost:5173"}
    first = auth_client.post("/api/admin/auth/login", json={"username": "admin", "password": "wrong"}, headers=headers)
    second = auth_client.post("/api/admin/auth/login", json={"username": "nobody", "password": "wrong"}, headers=headers)
    assert first.status_code == second.status_code == 401
    assert first.json() == second.json()
    assert first.headers["cache-control"] == "no-store"


def test_disabled_login_is_a_real_http_503_without_cache(monkeypatch: pytest.MonkeyPatch, auth_client: TestClient) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD_LOGIN_ENABLED", "false")
    get_settings.cache_clear()
    response = auth_client.post(
        "/api/admin/auth/login",
        json={"username": "admin", "password": "correct horse"},
        headers={"Origin": "http://localhost:5173"},
    )
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"


def test_success_clears_username_failure_bucket(auth_client: TestClient) -> None:
    headers = {"Origin": "http://localhost:5173"}
    for _ in range(4):
        assert auth_client.post("/api/admin/auth/login", json={"username": "admin", "password": "wrong"}, headers=headers).status_code == 401
    assert auth_client.post("/api/admin/auth/login", json={"username": "admin", "password": "correct horse"}, headers=headers).status_code == 200
    assert auth_client.post("/api/admin/auth/login", json={"username": "admin", "password": "wrong"}, headers=headers).status_code == 401


def test_cookie_session_requires_csrf_and_rejects_basic_fallback(auth_client: TestClient) -> None:
    headers = {"Origin": "http://localhost:5173"}
    login_response = auth_client.post("/api/admin/auth/login", json={"username": "admin", "password": "correct horse"}, headers=headers)
    assert login_response.status_code == 200
    csrf = login_response.json()["csrf_token"]
    assert auth_client.get("/protected", headers=headers).status_code == 200
    assert auth_client.post("/protected", headers=headers).status_code == 403
    assert auth_client.post("/protected", headers={**headers, "X-CSRF-Token": csrf}).status_code == 200
    assert auth_client.get("/protected", headers={**headers, "Authorization": "Basic bad"}).status_code == 401
    assert auth_client.post("/api/admin/auth/logout", headers={**headers, "X-CSRF-Token": csrf}).status_code == 200
    assert auth_client.get("/protected", headers=headers).status_code == 401


def test_busy_password_slots_fail_closed_with_retry_after(monkeypatch: pytest.MonkeyPatch, auth_client: TestClient) -> None:
    monkeypatch.setattr(auth_module, "_password_slots", __import__("asyncio").Semaphore(0))
    response = auth_client.post(
        "/api/admin/auth/login",
        json={"username": "admin", "password": "correct horse"},
        headers={"Origin": "http://localhost:5173"},
    )
    assert response.status_code == 429
    assert response.headers["retry-after"] == "1"


def test_untrusted_origin_has_no_cors_read_access(auth_client: TestClient) -> None:
    response = auth_client.get("/protected", headers={"Origin": "https://evil.invalid"})
    assert response.status_code == 401
    assert "access-control-allow-origin" not in response.headers
    slash_variant = auth_client.post(
        "/api/admin/auth/login",
        json={"username": "admin", "password": "correct horse"},
        headers={"Origin": "http://localhost:5173/"},
    )
    assert slash_variant.status_code == 403


def test_actual_admin_app_auth_middleware_adds_no_store_and_cors(monkeypatch: pytest.MonkeyPatch) -> None:
    from contextlib import asynccontextmanager

    from app import admin_main
    monkeypatch.setenv("ADMIN_PASSWORD_LOGIN_ENABLED", "true")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", _hash("correct horse"))
    monkeypatch.setenv("ADMIN_SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("ADMIN_AUTH_ALLOWED_ORIGINS", "http://localhost:5173")
    get_settings.cache_clear()

    @asynccontextmanager
    async def no_database_lifespan(_app):
        yield

    monkeypatch.setattr(admin_main.app.router, "lifespan_context", no_database_lifespan)
    with TestClient(admin_main.app) as client:
        login_response = client.post(
            "/api/admin/auth/login",
            json={"username": "admin", "password": "correct horse"},
            headers={"Origin": "http://localhost:5173"},
        )
        assert login_response.status_code == 200
        csrf = login_response.json()["csrf_token"]
        assert client.get("/api/admin/auth/me", headers={"Origin": "http://localhost:5173"}).status_code == 200
        response = client.get("/api/admin/auth/me", headers={"Origin": "https://evil.invalid"})
        client2 = TestClient(admin_main.app)
        client2.cookies.update(client.cookies)
        logout = client.post(
            "/api/admin/auth/logout",
            headers={"Origin": "http://localhost:5173", "X-CSRF-Token": csrf},
        )
        assert logout.status_code == 200
        assert client2.get("/api/admin/auth/me", headers={"Origin": "http://localhost:5173"}).status_code == 401
        expired = session_store.create("admin", ttl_seconds=60, now=0)
        client.cookies.set(session_cookie_name(get_settings()), expired.session_id)
        assert client.get("/api/admin/auth/me", headers={"Origin": "http://localhost:5173"}).status_code == 401
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "access-control-allow-origin" not in response.headers


def test_logout_is_idempotent_for_missing_session_but_requires_origin(auth_client: TestClient) -> None:
    assert auth_client.post("/api/admin/auth/logout", headers={"Origin": "http://localhost:5173"}).status_code == 200
    response = auth_client.post("/api/admin/auth/logout")
    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"


def test_expired_session_cannot_write_but_logout_is_idempotent(auth_client: TestClient) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    expired = session_store.create("admin", ttl_seconds=60, now=0)
    auth_client.cookies.set(session_cookie_name(settings), expired.session_id)
    headers = {"Origin": "http://localhost:5173", "X-CSRF-Token": expired.csrf_token}
    assert auth_client.post("/protected", headers=headers).status_code == 401
    assert auth_client.post("/api/admin/auth/logout", headers={"Origin": "http://localhost:5173"}).status_code == 200
