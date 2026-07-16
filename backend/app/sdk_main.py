"""
SDK API 服务入口 — 端口 8100
"""
import uvicorn
from fastapi import FastAPI
from app.api.sdk import version, config, click, log


class RequestSizeLimitMiddleware:
    """纯 ASGI 中间件：限制请求体大小，超限返回413

    策略：Content-Length 只用于提前拒绝明显超限/非法请求，
    所有放行请求都走 limited_receive 累计实际字节，防止虚假 CL 绕过。
    """
    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        cl = headers.get(b"content-length")

        # Content-Length 只用于快速拒绝超限/非法，不用于跳过实际计数
        if cl is not None:
            try:
                cl_int = int(cl.decode())
                if cl_int < 0:
                    await self._send_error(send, 400, "Invalid Content-Length")
                    return
                if cl_int > self.max_bytes:
                    await self._send_error(send, 413, "Request body too large")
                    return
                # 即使 CL 合法且≤max，仍走 limited_receive 累计实际字节
            except (ValueError, UnicodeDecodeError):
                await self._send_error(send, 400, "Invalid Content-Length header")
                return

        # 所有放行请求都累计实际字节
        exceeded = False
        total = 0

        async def limited_receive():
            nonlocal total, exceeded
            if exceeded:
                # 已超限，消费剩余 body 并返回 disconnect
                msg = await receive()
                while msg.get("more_body", False):
                    msg = await receive()
                return {"type": "http.disconnect"}
            message = await receive()
            if message.get("type") == "http.request":
                body = message.get("body", b"")
                total += len(body)
                if total > self.max_bytes:
                    exceeded = True
                    more = message.get("more_body", False)
                    while more:
                        msg = await receive()
                        more = msg.get("more_body", False)
                    return {"type": "http.disconnect"}
            return message

        # 包装 send 以拦截 app 响应（超限时替换为 413）
        async def _wrapped_send(message):
            nonlocal exceeded
            if exceeded:
                if message.get("type") == "http.response.start":
                    # 只发送一次 413，忽略后续
                    exceeded = False  # 防止重复
                    await self._send_error(send, 413, "Request body too large")
                return  # 超限后丢弃 app 的所有 send 消息
            await send(message)

        await self.app(scope, limited_receive, _wrapped_send)

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
