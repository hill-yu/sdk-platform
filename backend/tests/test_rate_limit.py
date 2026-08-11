"""限流 + 健康豁免 + 全部拒绝语义的自动化测试"""
from types import SimpleNamespace

import pytest

from app.core.database import get_db
from app.core.rate_limit import SimpleRateLimiter
from tests.conftest import StubReadSession, StubWriteSession, override_read_db, override_write_db


def _request_for_ip(ip: str):
    return SimpleNamespace(client=SimpleNamespace(host=ip))


@pytest.mark.asyncio
async def test_rate_limit_cleanup_removes_stale_ip_keys():
    """全局清理会过滤所有 IP 的过期时间戳，并删除空键"""
    now = 0.0
    limiter = SimpleRateLimiter(max_requests=10, window_seconds=1, clock=lambda: now)

    for i in range(999):
        await limiter(_request_for_ip(f"10.0.0.{i}"))

    assert len(limiter._store) == 999

    now = 10.0
    await limiter(_request_for_ip("10.1.0.1"))

    assert len(limiter._store) == 1
    assert "10.1.0.1" in limiter._store


@pytest.mark.asyncio
async def test_rate_limit_window_recovers_after_expiration():
    """时间窗口过期后，同一 IP 可以重新请求"""
    now = 0.0
    limiter = SimpleRateLimiter(max_requests=2, window_seconds=1, clock=lambda: now)
    request = _request_for_ip("10.0.0.1")

    await limiter(request)
    await limiter(request)

    with pytest.raises(Exception) as exc_info:
        await limiter(request)
    assert getattr(exc_info.value, "status_code", None) == 429

    now = 1.1
    await limiter(request)
    assert len(limiter._store["10.0.0.1"]) == 1


def test_rate_limit_cleanup_caps_ip_key_count():
    """容量超过上限时，清理保留最新的 IP 键"""
    limiter = SimpleRateLimiter(max_requests=10, window_seconds=100, max_keys=2, clock=lambda: 10.0)
    limiter._store["oldest"] = [1.0]
    limiter._store["middle"] = [2.0]
    limiter._store["newest"] = [3.0]

    limiter.cleanup(10.0)

    assert set(limiter._store) == {"middle", "newest"}


def test_rate_limit_returns_429_after_exceed(client):
    """连续请求超过限制后返回429"""
    # 清理限流器状态，避免跨测试污染
    from app.api.sdk.click import write_limiter as click_limiter

    click_limiter._store.clear()

    session = StubWriteSession()
    client.app.dependency_overrides[get_db] = override_write_db(session)

    try:
        # 发送 10 次合法请求（刚好到限额）
        for i in range(10):
            resp = client.post(
                "/api/v1/click",
                json={
                    "package_name": "test",
                    "device_id": f"dev-{i}",
                    "events": [{"type": "click", "page": "home", "element": "btn"}],
                },
            )
            assert resp.status_code == 200, f"第{i+1}次请求应返回200，实际{resp.status_code}"

        # 第 11 次应被限流
        resp = client.post(
            "/api/v1/click",
            json={
                "package_name": "test",
                "device_id": "dev-overflow",
                "events": [{"type": "click", "page": "home", "element": "btn"}],
            },
        )
        assert resp.status_code == 429, f"超出限额应返回429，实际{resp.status_code}"
    finally:
        click_limiter._store.clear()
        client.app.dependency_overrides.clear()


def test_health_check_exempt_from_rate_limit(client):
    """/health 不受限流影响"""
    # 发送 20 次 /health 请求，全部应返回 200
    for _ in range(20):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


def test_all_events_rejected_returns_error_code(client):
    """所有事件校验失败返回4001而非code=0"""
    # 清理限流器状态
    from app.api.sdk.click import write_limiter as click_limiter

    click_limiter._store.clear()

    session = StubWriteSession()
    client.app.dependency_overrides[get_db] = override_write_db(session)

    try:
        resp = client.post(
            "/api/v1/click",
            json={
                "package_name": "test",
                "device_id": "dev-1",
                "events": [
                    {"type": "click"},  # 无 page 无 element → 校验失败
                    {"type": "click"},  # 无 page 无 element → 校验失败
                ],
            },
        )
        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == 4001
        assert body["message"] == "all_events_rejected"
        assert body["data"]["accepted"] == 0
        assert body["data"]["rejected"] == 2
    finally:
        click_limiter._store.clear()
        client.app.dependency_overrides.clear()


def test_log_route_uses_shared_rate_limit_bucket(client):
    """click 与 log 共享同一个写入限流桶"""
    from app.api.sdk.click import write_limiter as click_limiter

    click_limiter._store.clear()
    session = StubWriteSession()
    client.app.dependency_overrides[get_db] = override_write_db(session)

    try:
        for i in range(10):
            resp = client.post(
                "/api/v1/click",
                json={
                    "package_name": "test",
                    "device_id": f"click-{i}",
                    "events": [{"type": "click", "page": "home", "element": "btn"}],
                },
            )
            assert resp.status_code == 200

        resp = client.post(
            "/api/v1/log",
            json={
                "package_name": "test",
                "device_id": "log-overflow",
                "logs": [{"level": "info", "message": "overflow"}],
            },
        )
        assert resp.status_code == 429
    finally:
        click_limiter._store.clear()
        client.app.dependency_overrides.clear()


def test_read_routes_exempt_from_write_rate_limit(client, dependency_keys):
    """配置和版本读取接口不消耗写入限流配额"""
    from app.core.database import get_db_no_commit
    from app.api.sdk.click import write_limiter as click_limiter

    click_limiter._store.clear()
    session = StubWriteSession()
    client.app.dependency_overrides[get_db_no_commit] = override_read_db(StubReadSession(None))
    client.app.dependency_overrides[get_db] = override_write_db(session)

    try:
        headers = {"Authorization": "Bearer sdk-config-test-token-1234567890"}
        for _ in range(20):
            assert client.post("/api/v1/config/meta", json={"package_name": "com.example.test"}, headers=headers).status_code == 404
            assert client.get("/api/v1/version", params={"platform": "ios"}).status_code == 200

        resp = client.post(
            "/api/v1/click",
            json={
                "package_name": "test",
                "device_id": "dev-after-reads",
                "events": [{"type": "click", "page": "home", "element": "btn"}],
            },
        )
        assert resp.status_code == 200
    finally:
        click_limiter._store.clear()
        client.app.dependency_overrides.clear()


def test_click_db_execute_failure_rolls_back_and_returns_500(client):
    """click 批量写入失败时 rollback，并返回 500"""
    from app.api.sdk.click import write_limiter as click_limiter

    class FailingExecuteSession(StubWriteSession):
        async def execute(self, *_args, **_kwargs):
            raise RuntimeError("simulated execute failure")

    click_limiter._store.clear()
    session = FailingExecuteSession()
    client.app.dependency_overrides[get_db] = override_write_db(session)

    try:
        resp = client.post(
            "/api/v1/click",
            json={
                "package_name": "test",
                "device_id": "dev-db-fail",
                "events": [{"type": "click", "page": "home", "element": "btn"}],
            },
        )
        assert resp.status_code == 500
        assert session.rolled_back is True
    finally:
        click_limiter._store.clear()
        client.app.dependency_overrides.clear()
