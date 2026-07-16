"""
SDK API 服务入口 — 端口 8100
"""
import uvicorn
from fastapi import FastAPI
from app.api.sdk import version, config, click, log
from app.core.middleware import RequestSizeLimitMiddleware


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
