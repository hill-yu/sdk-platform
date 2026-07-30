# SDK 数据中台第九次代码审阅报告

> 审阅日期：2026-07-21  
> 审阅对象：`26-EIGHTH-REVIEW-FEEDBACK.md` 及提交 `f3ef611` 至 `1fce67b` 后的代码  
> 审阅范围：commit 失败恢复、SDK 写入异常、应用/Nginx 限流、测试有效性

## 1. 审阅结论

本轮确认：rollback 后 ORM ID 访问、SDK 写入异常吞噬、recovery 结果日志区分等修改已实际落地；后端 33 项测试通过，前端生产构建通过。

但 26 号文档关于“SDK 滥用控制已修复”和“48 项、0 剩余”的结论不成立。新限流实现存在未处理异常、错误作用范围和内存无界增长问题，同时仍未实现客户端身份认证/签名及 app 配额。当前发现 **3 项必须修复、5 项建议修改**，不建议按“全部关闭”状态上线。

| 级别 | 数量 | 上线影响 |
|---|---:|---|
| 必须修复 | 3 | 限流可返回 500、可误伤读接口、滥用控制仍不完整 |
| 建议修改 | 5 | 影响内存、多进程一致性、测试可信度与错误语义 |
| 已确认修复 | 3 | ORM ID、写入异常、recovery 日志分支 |

## 2. 必须修复

### 2.1 [必须修复] middleware 中抛 HTTPException，限流请求变成未处理异常/500

**位置：**

- `backend/app/sdk_main.py:16-20`
- `backend/app/core/rate_limit.py:16-19`

当前函数式 HTTP middleware 在调用 `call_next()` 之前执行：

```python
await limiter(request)
```

限流器超限时直接 `raise HTTPException(429, ...)`。FastAPI 的异常处理层位于该用户 middleware 内部，无法捕获发生在 `call_next()` 之前的异常，因此不能保证转换为 429 响应。

本轮实际连续请求 `/health` 的探针在第 11 次得到：

```text
fastapi.exceptions.HTTPException: 429: Too many requests
ExceptionGroup: unhandled errors in a TaskGroup
```

也就是说，26 号报告所述“第 11 次返回 429”与当前代码实际行为不符。

**修复建议：** middleware 直接 `return JSONResponse(status_code=429, ...)`；或者把限流器作为目标路由的 `Depends()`，让 FastAPI 路由异常处理器接管。必须增加自动化测试并设置 `raise_server_exceptions=False`，断言真实 HTTP 状态为 429、响应体合法且没有异常逃逸。

### 2.2 [必须修复] 限流挂在整个 SDK 应用，误伤健康检查和只读配置接口

26 号报告声称保护 `/api/v1/click` 和 `/api/v1/log`，实际 `@app.middleware("http")` 会限制全部路径，包括：

- `/health`；
- SDK 版本查询；
- SDK 配置元数据查询；
- click/log 写入。

同一 NAT 出口下的正常客户端会共享一个 IP 配额；高频上报可能连带阻断配置更新和健康检查。健康检查被 429/500 会导致负载均衡器误判实例不健康并摘除节点。

**修复建议：** 仅对两个写入路由挂依赖或按 path/method 精确过滤；`/health` 必须豁免。Nginx 也应为写入 location 单独定义规则，而不是将所有 SDK API 混为一个共享桶。

### 2.3 [必须修复] “滥用控制”只实现 IP 限流，客户端身份与配额仍缺失

上一轮最低条件包括 app_id/API key 或带时间戳签名、速率限制、单 app 配额和告警。当前仅实现 IP 限流：任意客户端仍可伪造任意 `app_id` 写入，攻击者也可以通过代理池/IPv6 来源绕过单 IP 阈值。

**修复建议：**

1. 为每个 app 分配可轮换密钥，校验 `app_id + timestamp + nonce + body hash` 的 HMAC 签名。
2. 限制时间偏差并保存短期 nonce，防止重放。
3. 按 app_id 和 IP 双维度限流、配额及告警。
4. 密钥只保存散列或放入密钥管理系统，提供吊销流程。

如果产品明确接受匿名采集，应在威胁模型中记录该决定，并至少通过网关令牌、设备注册或其他机制控制来源；不能把 10 次/秒的单进程内存计数器视为完整鉴权。

## 3. 建议修改

### 3.1 [建议修改] IP 字典键永久保留，来源数量可导致内存无界增长

`SimpleRateLimiter` 只清理“当前 IP”的过期时间戳，从不删除其他 IP 的空列表。本轮探针依次模拟 2,000 个 IP，等待窗口过期后再访问一个新 IP：

```text
stored_ip_keys_after_expiry = 2001
```

建议使用带最大容量和 TTL 的缓存，或周期清理空键；生产环境优先交给 Nginx/Redis 等有界实现。

### 3.2 [建议修改] 单进程内存限流在多 worker 下不一致

每个 Uvicorn/Gunicorn worker 有独立 `_store`，实际限额会随 worker 数量增加；实例扩容后也会成倍放大。应用级限流若作为安全控制，应使用 Redis 原子计数/令牌桶，或明确以 Nginx 为唯一强制层。

### 3.3 [建议修改] 所有 click 事件校验失败仍返回 partial_success

`click.py` 删除了原来的“全部拒绝”分支。当所有事件都因缺少 `page/element` 被拒绝时，会返回 HTTP 200、`code=0`、`message=partial_success`，尽管 `accepted=0`。建议恢复全部拒绝语义并返回 4xx 或明确非零业务码。

### 3.4 [建议修改] commit 失败所需 ID 应在 commit 前缓存

当前把 `config_id = config.id` 放在 `await db.commit()` 已抛异常之后、rollback 之前。它解决了显式 rollback 造成的 expire，但 commit 内部可能包含 flush，失败状态下 ORM 生命周期仍依赖具体异常阶段。

建议在进入 `try: await db.commit()` 之前缓存 ID，使恢复路径完全不依赖失败 commit 后的 ORM 状态。

### 3.5 [建议修改] 新增关键路径没有自动化测试

本轮提交没有新增以下测试：

- 第 11 次请求真实返回 429；
- `/health` 和读接口不受写入限流影响；
- 时间窗口过后允许请求；
- IP 键被回收；
- 数据库 execute 异常时 rollback 且返回 500；
- 所有事件被校验拒绝时的响应语义。

26 号文档只记录 curl 手测，但当前探针已证明该结论与代码不一致。

## 4. 已确认修复

### 4.1 rollback 后不再读取原 ORM ID

两个 recovery 分支均缓存并使用局部 `config_id`，上一轮明确指出的 rollback 后访问问题已基本关闭；建议按 3.4 再把缓存位置前移。

### 4.2 SDK 数据库写入异常不再被吞掉

click/log 在 `db.execute()` 失败后显式 rollback 并抛出 HTTP 500。依赖层收到异常后不会执行正常 commit；重复 rollback 通常是幂等的，不再存在 aborted transaction 上继续 commit 的旧问题。

### 4.3 recovery 已区分记录不存在和写入异常

记录不存在会记录 error 并返回专门错误，独立事务异常会记录 critical，成功后才记录“失败状态已持久化”。该日志分支比上一版准确。

## 5. 验证记录

### 5.1 后端测试

```text
python -m pytest backend/tests -q
33 passed in 4.61s
```

### 5.2 前端构建

```text
npm run build
656 modules transformed
构建成功，主 JS 683.71 kB，gzip 237.20 kB
```

仍存在大于 500 kB 的 chunk 警告。

### 5.3 限流探针

```text
stored_ip_keys_after_expiry = 2001
第 11 次 /health：HTTPException 429 从 middleware 逃逸
结果：ExceptionGroup / 未处理异常，而非正常 429 Response
```

## 6. 下一轮最低验收条件

1. 限流命中必须稳定返回 HTTP 429，不产生未处理异常或 500。
2. 限流仅覆盖 click/log 写接口，健康检查和必要读接口豁免。
3. 补 app 身份认证/签名、重放防护、app/IP 双维度配额与告警，或形成经批准的匿名采集威胁模型。
4. 限流状态有 TTL 和容量上限，多 worker/多实例行为明确。
5. 恢复“全部事件被拒绝”的正确响应语义。
6. 增加上述自动化测试；后端完整测试保持 0 failed，前端构建保持成功。

**最终判断：当前不建议以“48 项问题全部关闭”的状态上线。**

