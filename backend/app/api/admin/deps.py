from __future__ import annotations

import hashlib
import hmac

from fastapi import Cookie, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings
from app.services.admin_auth_service import SessionStore, StoredSession


bearer_scheme = HTTPBearer(auto_error=False)
session_store = SessionStore()


def session_cookie_name(settings=None) -> str:
    settings = settings or get_settings()
    return "__Host-admin_session" if settings.ADMIN_SESSION_COOKIE_SECURE else "admin_session"


def allowed_origins(settings=None) -> set[str]:
    settings = settings or get_settings()
    return {origin.strip() for origin in settings.ADMIN_AUTH_ALLOWED_ORIGINS.split(",") if origin.strip()}


def require_allowed_origin(request: Request) -> None:
    origin = request.headers.get("origin", "")
    if not origin or origin not in allowed_origins():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Origin not allowed")


def _unauthorized(detail: str = "Authentication required") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"})


async def require_admin_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    settings = get_settings()
    raw_authorization = request.headers.get("authorization")
    if raw_authorization is not None:
        if credentials is None or credentials.scheme.lower() != "bearer" or not hmac.compare_digest(
            credentials.credentials.encode("utf-8"), settings.ADMIN_TOKEN.encode("utf-8")
        ):
            raise _unauthorized("Invalid admin token")
        return hashlib.sha256(credentials.credentials.encode()).hexdigest()[:8]

    session_id = request.cookies.get(session_cookie_name(settings))
    session: StoredSession | None = session_store.get(session_id)
    if session is None:
        raise _unauthorized()
    if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
        require_allowed_origin(request)
        if not hmac.compare_digest(
            request.headers.get("x-csrf-token", "").encode("utf-8"), session.csrf_token.encode("utf-8")
        ):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")
    return "admin-session"
