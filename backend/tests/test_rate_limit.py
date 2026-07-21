"""限流 + 健康豁免 + 全部拒绝语义的自动化测试"""
from app.core.database import get_db
from tests.conftest import StubWriteSession, override_write_db


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
                    "app_id": "test",
                    "device_id": f"dev-{i}",
                    "events": [{"type": "click", "page": "home", "element": "btn"}],
                },
            )
            assert resp.status_code == 200, f"第{i+1}次请求应返回200，实际{resp.status_code}"

        # 第 11 次应被限流
        resp = client.post(
            "/api/v1/click",
            json={
                "app_id": "test",
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
                "app_id": "test",
                "device_id": "dev-1",
                "events": [
                    {"type": "click"},  # 无 page 无 element → 校验失败
                    {"type": "click"},  # 无 page 无 element → 校验失败
                ],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 4001
        assert body["message"] == "all_events_rejected"
        assert body["data"]["accepted"] == 0
        assert body["data"]["rejected"] == 2
    finally:
        click_limiter._store.clear()
        client.app.dependency_overrides.clear()
