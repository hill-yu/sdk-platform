"""
SDK API 服务入口 — 端口 8100
"""
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from app.api.sdk import version, config, click, log


class RequestSizeExceeded(Exception):
    def __init__(self, max_bytes: int):
        self.max_bytes = max_bytes


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int):
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        # 1. 检查 Content-Length（快速拦截）
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_bytes:
                    return JSONResponse(status_code=413, content={"detail": f"Request body too large"})
                if int(content_length) < 0:
                    return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length"})
            except ValueError:
                return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length header"})

        # 2. 包装 receive 累计实际字节数
        total = 0
        original_receive = request.receive

        async def limited_receive():
            nonlocal total
            message = await original_receive()
            if message.get("type") == "http.request" and message.get("body"):
                total += len(message["body"])
                if total > self.max_bytes:
                    raise RequestSizeExceeded(self.max_bytes)
            return message

        request._receive = limited_receive

        try:
            return await call_next(request)
        except RequestSizeExceeded:
            return JSONResponse(status_code=413, content={"detail": f"Request body too large"})


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
