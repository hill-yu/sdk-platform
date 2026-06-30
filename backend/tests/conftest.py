from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient


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

    def begin_nested(self) -> StubNestedTransaction:
        return StubNestedTransaction()

    def add(self, record: Any) -> None:
        if self.fail_predicate(record):
            raise RuntimeError("simulated write failure")
        self.records.append(record)


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

