"""
SDK API 服务入口 — 端口 8100
"""
import uvicorn
from fastapi import FastAPI
from app.api.sdk import version, config, click, log


class _RequestSizeExceeded(Exception):
    pass


class RequestSizeLimitMiddleware:
    """纯 ASGI 中间件：限制请求体大小，超限返回413"""
    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Content-Length 快速拦截
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

        # 包装 receive 累计实际字节数
        total = 0
        async def limited_receive():
            nonlocal total
            message = await receive()
            if message.get("type") == "http.request":
                body = message.get("body", b"")
                total += len(body)
                if total > self.max_bytes:
                    # 读完剩余body后抛异常（被外层except捕获 → 413）
                    more = message.get("more_body", False)
                    while more:
                        msg = await receive()
                        more = msg.get("more_body", False)
                    raise _RequestSizeExceeded()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _RequestSizeExceeded:
            await self._send_error(send, 413, "Request body too large")

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
