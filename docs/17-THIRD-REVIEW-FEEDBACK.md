# 对 16-THIRD-REVIEW-REPORT-20260716.md 的分析反馈

> 日期：2026-07-16 | 分析人：汉堡包 🍔

---

## 总体评价

审阅人通过分块请求探针暴露了我 3.3 修复的残余问题——`BaseHTTPMiddleware` 的 `call_next()` 在独立任务中运行，自定义异常无法跨任务传播，导致 500。这是 FastAPI/Starlette 中间件的已知陷阱，我的实现没有避开。

关于 3.2 跨系统一致性，审阅人的分析正确——无论 "DB 先" 还是 "COS 先"，单靠顺序无法实现原子性。但完整状态机对当前规模过度设计。

**接受全部 2 项"必须修复"和 4 项"建议修改"。**

---

## 逐条分析

### 3.1 [必须修复] 分块超限返回 500 → 纯 ASGI 中间件

**根因**：`BaseHTTPMiddleware.call_next()` 在独立 task 中运行，`RequestSizeExceeded` 被 TaskGroup 包装后变成 `ExceptionGroup`，无法被外层 `except` 捕获。

**修复**：写纯 ASGI 中间件（函数式），直接包装 `receive`，在调用下游 `app(scope, receive, send)` 之前完成拦截。

```python
class RequestSizeLimitMiddleware:
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
        if cl:
            try:
                if int(cl) > self.max_bytes:
                    await self._send_413(send)
                    return
                if int(cl) < 0:
                    await self._send_400(send, "Invalid Content-Length")
                    return
            except ValueError:
                await self._send_400(send, "Invalid Content-Length header")
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
                    raise RequestSizeExceeded(self.max_bytes)
            return message
        
        try:
            await self.app(scope, limited_receive, send)
        except RequestSizeExceeded:
            await self._send_413(send)
    
    async def _send_413(self, send):
        await send({"type": "http.response.start", "status": 413, "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": b'{"detail":"Request body too large"}'})
    
    async def _send_400(self, send, msg: str):
        body = f'{{"detail":"{msg}"}}'.encode()
        await send({"type": "http.response.start", "status": 400, "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": body})
```

**使用**：`app.add_middleware(RequestSizeLimitMiddleware, max_bytes=1_000_000)` — Starlette 会自动包装纯 ASGI 中间件。

### 3.2 [必须修复] COS/DB 跨系统一致性 — 最小方案

全状态机对当前规模过度。采用最小可行方案：

1. **发布串行化**：`SELECT pg_try_advisory_xact_lock(9999)` 在发布事务中获取排他锁
2. **发布幂等**：用 `version` 作为 COS 对象 key 的幂等键（已存在）
3. **latest 更新幂等**：COS `put_object` 天然幂等
4. **失败重试**：COS 失败时重试 2 次，均失败则抛异常回滚
5. **对账**：定期任务比较 DB published 版本号与 COS latest.json 中的版本号

### 4.1 迁移脚本不可重复执行 — ✅ 用 DO 块保护 ADD CONSTRAINT

### 4.2 部署流程缺迁移 — ✅ 在 07-DEPLOYMENT.md 代码更新流程中增加迁移步骤

### 4.3 初始配置 pending → 改为 draft — ✅ 改为 draft，要求部署后通过管理后台手动发布

### 4.4 测试覆盖缺失 — ✅ 本轮加请求体限制测试和发布失败测试

---

> 🍔 分析完。逐项修复。
