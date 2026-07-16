"""
SDK API 服务入口 — 端口 8100
"""
import uvicorn
from fastapi import FastAPI
from app.api.sdk import version, config, click, log


class RequestSizeLimitMiddleware:
    """纯 ASGI 中间件：限制请求体大小，超限返回413

    策略：在调用 app 之前缓冲全部 body chunk。
    Content-Length 只用于快速拒绝明显超限/非法请求，
    放行后实际累计字节，超限则不调用 app 直接返回 413。
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

        # Content-Length 快速拒绝超限/非法
        if cl is not None:
            try:
                cl_int = int(cl.decode())
                if cl_int < 0:
                    await self._send_error(send, 400, "Invalid Content-Length")
                    return
                if cl_int > self.max_bytes:
                    await self._send_error(send, 413, "Request body too large")
                    return
            except (ValueError, UnicodeDecodeError):
                await self._send_error(send, 400, "Invalid Content-Length header")
                return

        # ① 缓冲全部 body chunk
        total = 0
        chunks = []
        more_body = True
        while more_body:
            message = await receive()
            if message.get("type") != "http.request":
                chunks.append(message)
                continue
            body = message.get("body", b"")
            total += len(body)
            more_body = message.get("more_body", False)
            # 超限：读完剩余后直接发 413（不调用 app）
            if total > self.max_bytes:
                while more_body:
                    msg = await receive()
                    more_body = msg.get("more_body", False)
                await self._send_error(send, 413, "Request body too large")
                return
            chunks.append(message)

        # ② 未超限：重放 body 给 app
        chunk_iter = iter(chunks)
        async def replay_receive():
            try:
                return next(chunk_iter)
            except StopIteration:
                return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay_receive, send)

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
