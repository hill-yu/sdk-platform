from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from threading import Lock


class AdminAuthConfigError(ValueError):
    pass


_N = 32768
_R = 8
_P = 1
_DKLEN = 32
_MAXMEM = 67108864


def _b64decode(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:
        raise AdminAuthConfigError("invalid password hash encoding") from exc


def parse_password_hash(value: str) -> tuple[bytes, bytes]:
    if not value:
        raise AdminAuthConfigError("ADMIN_PASSWORD_HASH is empty")
    parts = value.split("$")
    if len(parts) != 4 or parts[0] != "scrypt" or parts[1] != "N=32768,r=8,p=1":
        raise AdminAuthConfigError("unsupported ADMIN_PASSWORD_HASH format")
    salt, digest = _b64decode(parts[2]), _b64decode(parts[3])
    if len(salt) != 16 or len(digest) != _DKLEN:
        raise AdminAuthConfigError("invalid ADMIN_PASSWORD_HASH length")
    return salt, digest


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN, maxmem=_MAXMEM)
    encode = lambda value: base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
    return f"scrypt$N=32768,r=8,p=1${encode(salt)}${encode(digest)}"


async def _scrypt_verify(password: str, salt: bytes, expected: bytes) -> bool:
    candidate = await asyncio.to_thread(
        hashlib.scrypt,
        password.encode("utf-8"),
        salt=salt,
        n=_N,
        r=_R,
        p=_P,
        dklen=_DKLEN,
        maxmem=_MAXMEM,
    )
    return hmac.compare_digest(candidate, expected)


class AdminAuthService:
    def __init__(self, username: str, password_hash: str):
        self.username = username
        self.salt, self.digest = parse_password_hash(password_hash)

    async def verify(self, username: str, password: str) -> bool:
        matches = await _scrypt_verify(password, self.salt, self.digest)
        return matches and hmac.compare_digest(username.encode("utf-8"), self.username.encode("utf-8"))


@dataclass(frozen=True)
class SessionCredentials:
    session_id: str
    username: str
    created_at: float
    expires_at: float
    csrf_token: str


@dataclass(frozen=True)
class StoredSession:
    session_digest: str
    username: str
    created_at: float
    expires_at: float
    csrf_token: str


class SessionStore:
    def __init__(self, max_sessions: int = 1000):
        self.max_sessions = max_sessions
        self._sessions: dict[str, StoredSession] = {}
        self._lock = Lock()

    @staticmethod
    def _digest(session_id: str) -> str:
        return hashlib.sha256(session_id.encode("ascii")).hexdigest()

    def _purge(self, now: float) -> None:
        for key, session in list(self._sessions.items()):
            if session.expires_at <= now:
                del self._sessions[key]

    def create(self, username: str, ttl_seconds: int, now: float | None = None) -> SessionCredentials:
        now = time.time() if now is None else now
        with self._lock:
            self._purge(now)
            if len(self._sessions) >= self.max_sessions:
                raise RuntimeError("admin session capacity reached")
            session_id = secrets.token_urlsafe(32)
            session_digest = self._digest(session_id)
            stored = StoredSession(session_digest, username, now, now + ttl_seconds, secrets.token_urlsafe(32))
            self._sessions[session_digest] = stored
            return SessionCredentials(session_id, username, now, now + ttl_seconds, stored.csrf_token)

    def get(self, session_id: str | None, now: float | None = None) -> StoredSession | None:
        if not session_id:
            return None
        now = time.time() if now is None else now
        if not isinstance(session_id, str) or len(session_id) > 512 or any(ord(char) > 127 for char in session_id):
            return None
        digest = self._digest(session_id)
        with self._lock:
            self._purge(now)
            session = self._sessions.get(digest)
            if session is None or not hmac.compare_digest(session.session_digest, digest):
                return None
            return session

    def revoke(self, session_id: str | None) -> None:
        if isinstance(session_id, str) and len(session_id) <= 512 and all(ord(char) <= 127 for char in session_id):
            with self._lock:
                self._sessions.pop(self._digest(session_id), None)


class FailureRateLimiter:
    def __init__(self, max_failures: int = 5, window_seconds: int = 900, max_keys: int = 10000):
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._failures: dict[str, list[float]] = {}
        self._lock = Lock()

    def record_failure(self, key: str, now: float | None = None) -> int:
        now = time.time() if now is None else now
        with self._lock:
            self._purge(now)
            if key not in self._failures and len(self._failures) >= self.max_keys:
                return self.max_failures
            values = [item for item in self._failures.get(key, []) if item > now - self.window_seconds]
            values.append(now)
            self._failures[key] = values
            return len(values)

    def retry_after(self, key: str, now: float | None = None) -> int:
        now = time.time() if now is None else now
        with self._lock:
            self._purge(now)
            values = self._failures.get(key, [])
            if not values and key not in self._failures and len(self._failures) >= self.max_keys:
                return self.window_seconds
            if len(values) < self.max_failures:
                return 0
            return max(1, int(values[0] + self.window_seconds - now))

    def clear(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def _purge(self, now: float) -> None:
        cutoff = now - self.window_seconds
        for key, values in list(self._failures.items()):
            current = [item for item in values if item > cutoff]
            if current:
                self._failures[key] = current
            else:
                del self._failures[key]
