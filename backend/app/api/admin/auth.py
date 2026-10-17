from __future__ import annotations

import asyncio
import hmac
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.api.admin.deps import require_allowed_origin, session_cookie_name, session_store
from app.core.config import get_settings
from app.services.admin_auth_service import AdminAuthService, FailureRateLimiter

router = APIRouter(tags=["Admin - Auth"])
_limiter = FailureRateLimiter()
_ip_limiter = FailureRateLimiter(max_failures=30, window_seconds=900, max_keys=10000)
_password_slots = asyncio.Semaphore(4)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _service() -> AdminAuthService:
    settings = get_settings()
    return AdminAuthService(settings.ADMIN_USERNAME, settings.ADMIN_PASSWORD_HASH)


def _login_key(request: Request, username: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{host}:{username.strip().casefold()}"


def _ip_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/auth/login")
async def login(payload: LoginRequest, request: Request, response: Response):
    _no_store(response)
    require_allowed_origin(request)
    settings = get_settings()
    if not settings.ADMIN_PASSWORD_LOGIN_ENABLED:
        raise HTTPException(status_code=503, detail="Password login is not configured")
    key = _login_key(request, payload.username)
    ip_key = _ip_key(request)
    retry_after = max(_limiter.retry_after(key), _ip_limiter.retry_after(ip_key))
    if retry_after:
        raise HTTPException(status_code=429, detail="Too many login attempts", headers={"Retry-After": str(retry_after)})
    ip_count = _ip_limiter.record_failure(ip_key)
    if ip_count >= _ip_limiter.max_failures:
        retry_after = _ip_limiter.retry_after(ip_key)
        raise HTTPException(status_code=429, detail="Too many login attempts", headers={"Retry-After": str(retry_after)})
    try:
        await asyncio.wait_for(_password_slots.acquire(), timeout=0.05)
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=429, detail="Login capacity reached", headers={"Retry-After": "1"}) from exc
    try:
        valid = await _service().verify(payload.username, payload.password)
    finally:
        _password_slots.release()
    if not valid:
        count = _limiter.record_failure(key)
        if count >= _limiter.max_failures:
            retry_after = max(_limiter.retry_after(key), _ip_limiter.retry_after(ip_key))
            raise HTTPException(status_code=429, detail="Too many login attempts", headers={"Retry-After": str(retry_after)})
        raise HTTPException(status_code=401, detail="Invalid username or password")
    _limiter.clear(key)
    try:
        session = session_store.create(settings.ADMIN_USERNAME, settings.ADMIN_SESSION_TTL_SECONDS)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Session capacity reached") from exc
    response.set_cookie(
        key=session_cookie_name(settings),
        value=session.session_id,
        max_age=settings.ADMIN_SESSION_TTL_SECONDS,
        httponly=True,
        secure=settings.ADMIN_SESSION_COOKIE_SECURE,
        samesite="strict",
        path="/",
    )
    return {"username": session.username, "expires_at": session.expires_at, "csrf_token": session.csrf_token}


@router.get("/auth/me")
async def me(request: Request, response: Response):
    _no_store(response)
    settings = get_settings()
    session = session_store.get(request.cookies.get(session_cookie_name(settings)))
    if session is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return {"username": session.username, "expires_at": session.expires_at, "csrf_token": session.csrf_token}


@router.post("/auth/logout")
async def logout(request: Request, response: Response):
    _no_store(response)
    settings = get_settings()
    require_allowed_origin(request)
    session_id = request.cookies.get(session_cookie_name(settings))
    session = session_store.get(session_id)
    if session is not None:
        token = request.headers.get("x-csrf-token", "")
        if not token or not hmac.compare_digest(token.encode("utf-8"), session.csrf_token.encode("utf-8")):
            raise HTTPException(status_code=403, detail="Invalid CSRF token")
    session_store.revoke(session_id)
    response.delete_cookie(
        session_cookie_name(settings),
        path="/",
        secure=settings.ADMIN_SESSION_COOKIE_SECURE,
        httponly=True,
        samesite="strict",
    )
    return {"ok": True}
