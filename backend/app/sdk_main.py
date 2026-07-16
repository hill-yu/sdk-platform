"""
SDK API 服务入口 — 端口 8100
"""
import uvicorn
from fastapi import FastAPI
from app.api.sdk import version, config, click, log


class RequestSizeLimitMiddleware:
    """纯 ASGI 中间件：限制请求体大小，超限返回413

    策略：先缓冲全部 body，验证大小后重放给内部 app。
    Content-Length 合法时走快速路径跳过缓冲。
    """
    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # ── Content-Length 快速路径 ──
        headers = dict(scope.get("headers", []))
        cl = headers.get(b"content-length")
        if cl is not None:
            try:
                cl_int = int(cl.decode())
                if cl_int > self.max_bytes:
                    await self._send_error(send, 413, "Request body too large")
                    return
                if cl_int < 0:
                    await self._send_error(send, 400, "Invalid Content-Length")
                    return
            except (ValueError, UnicodeDecodeError):
                await self._send_error(send, 400, "Invalid Content-Length header")
                return
            # Content-Length 合法且在限制内 → 直接放行
            await self.app(scope, receive, send)
            return

        # ── 无 Content-Length（分块传输）→ 缓冲全部 body ──
        body_chunks: list[dict] = []
        total = 0

        while True:
            message = await receive()
            if message.get("type") == "http.disconnect":
                return
            if message.get("type") != "http.request":
                body_chunks.append(message)
                continue

            body = message.get("body", b"")
            total += len(body)
            if total > self.max_bytes:
                # 读完剩余 body 后返回 413
                more = message.get("more_body", False)
                while more:
                    msg = await receive()
                    more = msg.get("more_body", False)
                await self._send_error(send, 413, "Request body too large")
                return

            body_chunks.append(message)
            if not message.get("more_body", False):
                break

        # 重放缓冲的 body 给内部 app
        _iter = iter(body_chunks)

        async def replayed_receive():
            try:
                return next(_iter)
            except StopIteration:
                return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replayed_receive, send)

    async def _send_error(self, send, status: int, detail: str):
        body = f'{{"detail":"{detail}"}}'.encode()
        await send({"type": "http.response.start", "status": status,
                     "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": body})


app = FastAPI(title="SDK API", version="1.0.0")
app.add_middleware(RequestSizeLimitMiddleware, max_bytes=1_000_000)

app.include_router(version.router)
app.include_router(config.router)
app.include_router(click.router)
app.include_router(log.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8100)
