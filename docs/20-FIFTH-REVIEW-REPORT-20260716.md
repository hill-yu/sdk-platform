# SDK 数据中台第五次代码审阅报告

> 审阅日期：2026-07-16  
> 审阅对象：根据 `18-FOURTH-REVIEW-REPORT-20260716.md` 和 `19-FOURTH-REVIEW-FEEDBACK.md` 修改后的当前代码  
> 审阅范围：请求体 ASGI 中间件、配置发布/回滚、数据库提交失败处理、对账接口、部署流程、测试与前端构建  
> 审阅方法：提交与代码对照、完整测试、前端构建、真实 SDK 路由原始 ASGI 消息探针

---

## 1. 审阅结论

本轮修改完成了发布与回滚 advisory lock、COS 重试、显式数据库 commit、对账静态路由前置、异步 HTTP 客户端、迁移包部署以及 3 项配置服务测试。后端测试达到 30/30 通过，前端构建成功。

但是，`19-FOURTH-REVIEW-FEEDBACK.md` 所称“第四次审阅全部关闭”与实际代码不符。本次复审确认仍有 3 项必须修复问题：

1. 请求体中间件在真实 SDK 路由上发送两个响应 body，413 响应内容被下游错误体污染。
2. 数据库 commit 失败时 `cos_upload_status='failed'` 只修改内存对象，随后 rollback，不会形成持久化补偿，CDN/DB 仍不一致。
3. 对账接口读取的是版本化 CDN URL，不是 `config/latest.json`，无法发现本项目最关键的 latest 指针错位。

因此，虽然完整测试全绿，当前仍不建议上线。

### 1.1 风险汇总

| 级别 | 数量 | 上线影响 |
|---|---:|---|
| 必须修复 | 3 | 修复和验证前不建议上线 |
| 建议修改 | 5 | 建议上线前完成或明确纳入技术债 |
| 已确认修复 | 7 | 代码、部署文档或测试已实际落地 |

---

## 2. 对 19 号修复报告的复核

19 号文档首次提供了明确 commit、修复内容和测试数字，且对应提交均可在 Git 历史中找到。但修复验证仍存在“只检查状态码或单一内存状态，没有验证完整协议和持久化语义”的问题：

- 请求限制测试只断言第一个响应消息状态为 413，没有断言 ASGI 消息序列和最终 body。
- commit 失败处理没有测试，且代码没有 rollback 后的新事务持久化。
- 对账接口没有测试 URL 是否为 latest，也没有路由/API 行为测试。
- 配置失败测试覆盖 COS 失败，但没有覆盖 COS 成功后数据库 commit 失败。

本报告按实际运行结果重新判定问题状态，不以“30 passed”直接等同于全部问题关闭。

---

## 3. 必须修复

### 3.1 [必须修复] 超限请求产生两个响应 body，413 响应为非法 JSON

**位置**：

- `backend/app/sdk_main.py:42-78`
- `backend/app/admin_main.py:53-87`

当前中间件在实际 body 超限时，将 `limited_receive()` 的结果改为 `http.disconnect`，让下游 FastAPI 停止读取；同时 `_wrapped_send()` 在看到下游第一个 `http.response.start` 时发送完整 413 响应：

```python
if exceeded:
    if message.get("type") == "http.response.start":
        exceeded = False
        await self._send_error(send, 413, ...)
    return
```

问题在于发送 413 后立即把 `exceeded=False`。下游随后发送的 `http.response.body` 会走正常分支并被继续转发，从而追加到 413 body 后面。

#### 真实 SDK 路由探针

请求条件：

- 路径：`POST /api/v1/click`
- 应用限制：1,000,000 字节
- 声明 `Content-Length: 1`
- 实际 body：1,000,001 字节

实际 ASGI 消息：

```text
http.response.start  status=413
http.response.body   {"detail":"Request body too large"}
http.response.body   {"detail":"There was an error parsing the body"}
```

最终响应体会成为两个 JSON 对象的拼接，不是合法 JSON。不同 ASGI server/transport 还可能把这视为协议错误。

此外，使用自定义读取请求体的端点时，`ClientDisconnect` 可以直接逃出应用，说明 send 拦截仍依赖下游如何处理断开事件。

#### 为什么现有测试没有发现

`test_sdk_chunked_oversized_returns_413()` 和 Admin 对应测试只断言：

```python
assert responses[0]["status"] == 413
```

没有检查响应消息数量、`more_body`、最终合并 body 或异常是否逃逸。

#### 建议

建议回到更简单、协议完整的实现：在调用下游应用前缓冲请求体到上限加 1 字节；一旦超限，直接由中间件发送 413 并返回，不调用下游应用。对于声明长度正常或缺失的请求都执行同一实际字节验证。

必须增加：

- 最终响应只有一个 `http.response.start`。
- 最终 body 只有一个合法 JSON 对象。
- 下游端点不会被执行。
- 自定义读取 body 的端点不会抛 `ClientDisconnect`。
- SDK/Admin 实际路由在虚假小 Content-Length 下稳定返回 413。

### 3.2 [必须修复] commit 失败补偿不会持久化，DB/CDN 仍不一致

**位置**：

- `backend/app/services/config_service.py:105-112`
- `backend/app/services/config_service.py:162-169`
- `backend/app/core/database.py:32-40`

当前代码：

```python
try:
    await db.commit()
except Exception:
    config.cos_upload_status = "failed"
    raise HTTPException(status_code=500, ...)
```

数据库 commit 失败后，SQLAlchemy session/事务通常需要先 rollback。这里只修改 ORM 内存对象，没有 rollback，也没有开启新事务并再次 commit。随后抛出的 `HTTPException` 会被 `get_db()` 捕获并执行：

```python
await session.rollback()
```

因此 `cos_upload_status='failed'` 不会持久化。数据库恢复旧状态，而 COS `latest.json` 已经更新为新版本，原始不一致仍然存在。

#### 影响

- 管理后台看不到 failed 记录。
- 对账或人工恢复缺少待处理状态。
- 日志虽然提示“部分完成”，但系统没有可重试的持久化任务。
- 显式 commit 只是提前暴露错误，没有形成补偿。

#### 建议

仅在同一个业务记录上设置 failed 不足以处理原事务提交失败。建议使用独立发布记录/Outbox：

1. 在 COS 操作前持久化发布意图。
2. 每个阶段以独立事务更新状态。
3. latest 更新后数据库业务事务失败时，发布意图仍存在。
4. 后台任务按发布意图重试数据库或恢复 latest。
5. 对账发现不一致时生成可追踪的恢复任务。

若仍采用最小方案，至少需要 rollback 后使用新 session/新事务写入独立失败记录，并验证这个写入不会依赖已经失败的业务事务。

### 3.3 [必须修复] 对账读取版本化对象，无法检测 latest.json 错位

**位置**：

- `backend/app/api/admin/config_mgr.py:41-51`
- `backend/app/services/config_service.py:101-103、158-160`

配置发布后保存的 `published.cdn_url` 是：

```text
<CDN_BASE_URL>/config/v<version>.json
```

对账接口直接请求：

```python
cdn_url = published.cdn_url
r = await client.get(cdn_url)
```

这读取的是当前数据库版本对应的不可变对象。只要版本文件上传成功，它几乎必然与数据库版本一致，即使 `config/latest.json` 已经被其他请求覆盖或在 commit 失败后指向不同版本，对账仍会返回 `consistent=true`。

#### 影响

- 无法发现本轮修复要解决的核心问题：DB published 与 COS latest 不一致。
- commit 失败后，即使手工调用对账接口也可能得到错误的正常结论。
- 所谓对账机制不能作为发布补偿依据。

#### 建议

对账必须显式请求：

```text
<CDN_BASE_URL>/config/latest.json
```

同时使用缓存穿透策略，例如唯一查询参数和合适的 `Cache-Control`，避免读取 CDN 缓存旧值。响应中应同时返回：

- DB published version。
- latest.json version。
- published versioned object 是否存在。
- 是否一致。
- 检查时间与错误类型。

必须增加 latest 与 DB 一致、不一致、缺失、无 version 字段和 CDN 不可达测试。

---

## 4. 建议修改

### 4.1 [建议修改] rollback 重复获取同一事务级 advisory lock

**位置**：

- `backend/app/services/config_service.py:127`
- `backend/app/services/config_service.py:136`

`rollback_config()` 获取锁后调用 `_publish_from_record()`，后者再次获取同一把锁。PostgreSQL 同一事务可以重复获取 advisory lock，因此通常不会造成死锁，但逻辑重复且测试更难准确模拟。

建议只在统一的发布入口获取一次锁，内部函数假定调用方已经持锁，或把“获取锁 + 发布”封装为单一编排函数。

### 4.2 [建议修改] 对账仍不是定时任务

19 号文档写“定时任务记录技术债”，当前代码仍只有手工 GET 接口，没有周期调度、告警或自动恢复。它不应被描述为已经实现“定期对账”。

建议明确标记为未完成技术债，并在上线检查清单中要求外部监控定期调用；更稳妥的是在 Admin lifespan 中建立独立周期任务或使用系统 cron。

### 4.3 [建议修改] 对账错误把底层异常文本返回客户端

**位置**：`backend/app/api/admin/config_mgr.py:57-59`

接口把 `str(e)` 拼入响应：

```python
{"message": f"CDN不可达: {str(e)}"}
```

即使接口有 Admin Token，这也可能暴露 DNS、代理、TLS、内部连接地址等运行环境信息。建议日志记录完整异常，API 只返回稳定错误码和概括信息。

### 4.4 [建议修改] 发布成功日志早于外层依赖完成

Service 已显式 commit，当前成功日志与数据库提交位置一致，这比上轮更准确。但外层 `get_db()` 仍会再次 commit，事务职责依然混合。建议发布接口使用专门 session/事务边界，避免 Service 和 dependency 双重提交。

### 4.5 [建议修改] 发布测试声明与实际覆盖不一致

19 号文档称增加“发布失败/锁冲突/回滚 3 项”。实际新增测试覆盖：

- publish 获取锁失败。
- publish COS 上传失败。
- rollback COS 上传失败。

仍未覆盖：

- 数据库 commit 失败。
- failed 状态是否真实持久化。
- rollback 锁冲突。
- publish/rollback 并发。
- COS latest 成功但 DB commit 失败。
- 对账 latest 指针错位。

建议修复文档准确区分 COS 失败与数据库提交失败，并为持久化语义增加集成测试。

---

## 5. 已确认修复

### 5.1 所有请求均累计实际字节

中间件不再因为 Content-Length 合法且未超限就跳过实际字节累计。虚假小 Content-Length 已能触发超限状态；剩余问题是响应协议处理不完整。

### 5.2 publish 已增加 advisory lock

发布路径在 COS 操作前获取事务级 advisory lock，锁冲突返回 409。

### 5.3 rollback 已进入同一锁域

回滚入口和内部发布函数均请求相同 advisory lock。虽然存在重复获取，但与完全无锁相比已消除 publish/rollback 互不约束的问题。

### 5.4 COS 上传增加有限重试

版本文件和 latest.json 上传均通过 `_upload_with_retry()` 执行，默认失败后重试两次，总计最多三次尝试。

### 5.5 对账路由遮蔽已修复

`/configs/reconcile` 已移动到 `/configs/{config_id}` 之前，静态路由能够优先匹配。

### 5.6 对账网络调用改为异步

已使用 `httpx.AsyncClient` 替代同步 `urllib.request`，不会再阻塞 Admin API 事件循环。

### 5.7 对账数据库查询过滤 success

数据库查询同时限制 `status='published'` 和 `cos_upload_status='success'`，与 SDK 有效配置条件一致。

### 5.8 部署包已包含 scripts

部署文档打包命令已改为：

```bash
tar -czf sdk-deploy.tar.gz backend/ scripts/
```

迁移脚本能够随代码一并上传。

### 5.9 迁移执行门禁继续保留

部署流程在重启服务前执行 `migrate_cos_upload_status.sql`，失败则退出。

---

## 6. 验证记录

### 6.1 后端完整测试

```text
命令：python -m pytest backend/tests -q
结果：30 passed in 8.53s
结论：现有测试全部通过，但未覆盖本报告的三个必须修复场景
```

### 6.2 前端生产构建

```text
命令：npm run build
结果：构建成功，656 modules transformed
主 JS：约 683.71 kB，gzip 后约 237.20 kB
警告：chunk 超过 500 kB
结论：构建通过
```

### 6.3 真实 SDK 路由超限探针

```text
exception: none
messages:
1. http.response.start status=413
2. http.response.body {"detail":"Request body too large"}
3. http.response.body {"detail":"There was an error parsing the body"}
```

结论：状态码正确，但响应消息序列和最终 body 错误。

### 6.4 自定义 body 读取端点探针

使用同一中间件包装直接 `await request.json()` 的端点时，超限产生的 `ClientDisconnect` 可以逃出应用。说明当前方案依赖 FastAPI 请求解析层恰好把断开转换为错误响应。

### 6.5 代码语义验证

```text
commit 失败后的 failed 写入：无 rollback 后新事务、无二次 commit
对账请求 URL：published.cdn_url（版本化对象）
latest.json 对账：未实现
定时对账任务：未实现
```

### 6.6 未执行的外部验证

本轮没有连接真实 PostgreSQL、腾讯云 COS 或 Nginx，因此尚未验证：

- commit 失败后的真实 session 状态。
- advisory lock 的真实并发行为。
- COS 重试和 latest 缓存行为。
- 数据库迁移实际执行。
- Nginx 与应用双层请求限制。

---

## 7. 与 18 号报告问题的状态对照

| 18 号报告问题 | 当前状态 | 说明 |
|---|---|---|
| 虚假 Content-Length 绕过 | 部分修复 | 已检测超限，但响应产生双 body/潜在 ClientDisconnect |
| rollback 缺锁 | 已修复 | 已加入同一 advisory lock，但重复获取 |
| commit 失败无补偿 | 未修复 | failed 状态不持久化，CDN/DB 仍不一致 |
| 对账路由不可达 | 已修复 | 静态路由已前置 |
| 部署包缺 scripts | 已修复 | 已打包 backend + scripts |
| 对账非阻塞 | 已修复 | 改用 httpx AsyncClient |
| 对账 latest 错位 | 未修复 | 当前读取版本化对象，不是 latest.json |
| 发布失败测试缺失 | 部分修复 | 增加 COS 失败测试，commit/并发/对账仍缺失 |

---

## 8. 建议修复顺序

1. 改为在调用下游前完成 body 大小验证，保证单一合法 413 响应。
2. 为 commit 失败建立独立、可持久化的失败记录或 Outbox。
3. 对账改为读取 `config/latest.json`，并补一致/不一致测试。
4. 去除 rollback 重复锁获取，统一发布编排函数。
5. 增加 commit 失败、并发发布、rollback 锁冲突和对账测试。
6. 将对账接入定时任务和告警。
7. 在 PostgreSQL、COS/CDN、Nginx 测试环境完成端到端验证。

---

## 9. 上线判定

**当前判定：不建议上线。**

重新评估上线至少需要满足：

- 超限请求只产生一组合法 413 响应，不追加下游 body、不泄漏 ClientDisconnect。
- COS latest 成功而数据库 commit 失败时，有持久化、可重试的恢复记录。
- 对账真实比较 DB published 与 `config/latest.json`。
- publish/rollback 锁和并发行为具有回归测试。
- 数据库提交失败、对账不一致具有回归测试。
- 后端完整测试继续保持 0 failed。
- 完成 PostgreSQL、COS/CDN、Nginx 端到端验证。

