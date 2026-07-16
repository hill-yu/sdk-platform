"""测试请求体大小限制中间件（纯 ASGI，对应 Fix 3.1 + 4.4）"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


# ── SDK API (1MB 限制) ──────────────────────────────────────────


@pytest.mark.anyio
async def test_sdk_normal_request_passes():
    """正常大小的请求应该通过"""
    from app.sdk_main import app as sdk_app

    transport = ASGITransport(app=sdk_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/click",
            json={"app_id": "t", "device_id": "d", "events": [{"type": "click", "page": "p"}]},
        )
    assert r.status_code == 200


@pytest.mark.anyio
async def test_sdk_oversized_content_length_returns_413():
    """Content-Length 超过 1MB 应该返回 413"""
    from app.sdk_main import app as sdk_app

    transport = ASGITransport(app=sdk_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/click",
            content=b"x" * 1_100_000,
            headers={
                "Content-Length": "1100000",
                "Content-Type": "application/json",
            },
        )
    assert r.status_code == 413


@pytest.mark.anyio
async def test_sdk_chunked_oversized_returns_413():
    """分块传输超限（ASGI 模拟分块 body 累计超过 1MB）应该返回 413"""
    from app.sdk_main import app as sdk_app

    # 模拟分块 body：两段各 600KB，累计 > 1MB
    chunks = [
        {"type": "http.request", "body": b"x" * 600_000, "more_body": True},
        {"type": "http.request", "body": b"x" * 600_000, "more_body": False},
    ]
    _iter = iter(chunks)

    async def receive():
        try:
            return next(_iter)
        except StopIteration:
            # ASGI 规范：body 发完后 receive 可能被继续调用
            return {"type": "http.request", "body": b"", "more_body": False}

    responses: list[dict] = []

    async def send(message):
        responses.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/click",
        "raw_path": b"/api/v1/click",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "scheme": "http",
        "server": ("test", 80),
        "client": ("127.0.0.1", 12345),
        "http_version": "1.1",
    }

    await sdk_app(scope, receive, send)

    # 检查响应状态
    assert len(responses) >= 1
    assert responses[0]["status"] == 413


@pytest.mark.anyio
async def test_sdk_invalid_content_length_returns_400():
    """非法（非数字）Content-Length 应该返回 400"""
    from app.sdk_main import app as sdk_app

    transport = ASGITransport(app=sdk_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/click",
            content=b"{}",
            headers={
                "Content-Length": "not-a-number",
                "Content-Type": "application/json",
            },
        )
    assert r.status_code == 400


@pytest.mark.anyio
async def test_sdk_negative_content_length_returns_400():
    """负数 Content-Length 应该返回 400"""
    from app.sdk_main import app as sdk_app

    transport = ASGITransport(app=sdk_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/click",
            content=b"{}",
            headers={
                "Content-Length": "-1",
                "Content-Type": "application/json",
            },
        )
    assert r.status_code == 400


# ── Admin API (5MB 限制) ────────────────────────────────────────


@pytest.mark.anyio
async def test_admin_normal_request_passes():
    """Admin API 正常请求应通过"""
    from app.admin_main import app as admin_app

    transport = ASGITransport(app=admin_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/admin/health")
    assert r.status_code == 200


@pytest.mark.anyio
async def test_admin_oversized_content_length_returns_413():
    """Admin API Content-Length 超过 5MB 应该返回 413"""
    from app.admin_main import app as admin_app

    transport = ASGITransport(app=admin_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/admin/configs",
            content=b"x" * 5_100_000,
            headers={
                "Content-Length": "5100000",
                "Content-Type": "application/json",
            },
        )
    assert r.status_code == 413


@pytest.mark.anyio
async def test_admin_chunked_oversized_returns_413():
    """Admin API 分块传输超限（ASGI 模拟分块 body 累计超过 5MB）应该返回 413"""
    from app.admin_main import app as admin_app

    # 模拟分块 body：6 段各 1MB，累计 > 5MB
    chunks = [
        {"type": "http.request", "body": b"x" * 1_000_000, "more_body": True},
        {"type": "http.request", "body": b"x" * 1_000_000, "more_body": True},
        {"type": "http.request", "body": b"x" * 1_000_000, "more_body": True},
        {"type": "http.request", "body": b"x" * 1_000_000, "more_body": True},
        {"type": "http.request", "body": b"x" * 1_000_000, "more_body": True},
        {"type": "http.request", "body": b"x" * 1_000_000, "more_body": False},
    ]
    _iter = iter(chunks)

    async def receive():
        try:
            return next(_iter)
        except StopIteration:
            return {"type": "http.request", "body": b"", "more_body": False}

    responses: list[dict] = []

    async def send(message):
        responses.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/admin/configs",
        "raw_path": b"/api/admin/configs",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "scheme": "http",
        "server": ("test", 80),
        "client": ("127.0.0.1", 12345),
        "http_version": "1.1",
    }

    await admin_app(scope, receive, send)

    assert len(responses) >= 1
    assert responses[0]["status"] == 413


@pytest.mark.anyio
async def test_admin_invalid_content_length_returns_400():
    """Admin API 非法 Content-Length 应该返回 400"""
    from app.admin_main import app as admin_app

    transport = ASGITransport(app=admin_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/admin/configs",
            content=b"{}",
            headers={
                "Content-Length": "abc",
                "Content-Type": "application/json",
            },
        )
    assert r.status_code == 400


@pytest.mark.anyio
async def test_admin_negative_content_length_returns_400():
    """Admin API 负数 Content-Length 应该返回 400"""
    from app.admin_main import app as admin_app

    transport = ASGITransport(app=admin_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/admin/configs",
            content=b"{}",
            headers={
                "Content-Length": "-5",
                "Content-Type": "application/json",
            },
        )
    assert r.status_code == 400
