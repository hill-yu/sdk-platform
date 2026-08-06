from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

# ── Inject valid test credentials before any app import ──────────────
os.environ.setdefault("ADMIN_TOKEN", "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0")
os.environ.setdefault("SDK_CONFIG_TOKEN", "sdk-config-test-token-1234567890")
os.environ.setdefault("CDN_BASE_URL", "https://cdn.test.local")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import get_db, get_db_no_commit  # noqa: E402
from app.sdk_main import app  # noqa: E402


class StubScalarResult:
    def __init__(self, value: Any):
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class StubReadSession:
    def __init__(self, execute_result: Any):
        self.execute_result = execute_result

    async def execute(self, *_args: Any, **_kwargs: Any) -> StubScalarResult:
        return StubScalarResult(self.execute_result)


class StubNestedTransaction:
    async def __aenter__(self) -> "StubNestedTransaction":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class StubWriteSession:
    def __init__(self, fail_predicate: Callable[[Any], bool] | None = None):
        self.fail_predicate = fail_predicate or (lambda _record: False)
        self.records: list[Any] = []
        self.executed: list[Any] = []
        self.committed = False
        self.rolled_back = False

    def begin_nested(self) -> StubNestedTransaction:
        return StubNestedTransaction()

    def add(self, record: Any) -> None:
        if self.fail_predicate(record):
            raise RuntimeError("simulated write failure")
        self.records.append(record)

    async def execute(self, stmt, *args: Any, **kwargs: Any):
        from sqlalchemy.sql import Insert
        if isinstance(stmt, Insert):
            # For pg_insert with .values([...]), extract from compiled parameters
            try:
                compiled = stmt.compile(
                    dialect=stmt._dialect if hasattr(stmt, '_dialect') and stmt._dialect else None
                )
                params = compiled.params
                if isinstance(params, dict):
                    params = [params]
                for value_dict in params:
                    if isinstance(value_dict, dict) and self.fail_predicate(value_dict):
                        raise RuntimeError("simulated write failure")
                    if isinstance(value_dict, dict):
                        self.records.append(value_dict)
            except (AttributeError, KeyError, TypeError):
                pass  # 参数提取相关异常才忽略
        self.executed.append(stmt)
        return StubScalarResult(None)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True

    async def flush(self):
        pass

    async def close(self):
        pass


@pytest.fixture()
def client() -> TestClient:
    app.dependency_overrides.clear()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def override_read_db(session: StubReadSession):
    async def _override():
        yield session

    return _override


def override_write_db(session: StubWriteSession):
    async def _override():
        yield session

    return _override


@pytest.fixture()
def dependency_keys():
    return {"read": get_db_no_commit, "write": get_db}
