# SDK 数据中台第六次代码审阅报告

> 审阅日期：2026-07-16  
> 审阅对象：根据 `20-FIFTH-REVIEW-REPORT-20260716.md` 和 `21-FIFTH-REVIEW-FEEDBACK.md` 修改后的当前代码  
> 审阅范围：请求体缓冲中间件、数据库 commit 失败恢复、latest.json 对账、锁、测试及前端构建  
> 审阅方法：代码与提交逐项复核、完整测试、前端构建、ASGI 断连超时探针、事务生命周期分析

---

## 1. 审阅结论

本轮修改已经消除了超限响应双 body，latest 对账目标已改为 `config/latest.json`，rollback 重复锁已去除，commit 失败路径增加独立 session 记录，并补充了对账和 commit 失败测试。后端测试为 33/33 通过，前端构建成功。

但是，`21-FIFTH-REVIEW-FEEDBACK.md` 宣称“38 项、0 剩余”仍早于实际完成。本次复审发现 2 项必须修复问题：

1. 请求体缓冲循环不处理 `http.disconnect`，客户端断连时可无限循环并占用事件循环；超限后还会等待攻击者发送完剩余 body，无法及时返回 413。
2. commit 失败恢复在原事务 rollback 前启动新 session 更新同一行，可能等待原事务锁形成自锁；所谓“failed 已持久化”的测试只验证内存假对象赋值，没有验证真实事务提交。

此外，对账仍是手工接口，没有定时告警或恢复；恢复记录复用了业务配置行，不能可靠表达 COS 已上传但 DB 发布未完成的目标版本。

因此，当前仍不建议直接上线。

### 1.1 风险汇总

| 级别 | 数量 | 上线影响 |
|---|---:|---|
| 必须修复 | 2 | 修复和验证前不建议上线 |
| 建议修改 | 5 | 建议上线前完成或明确纳入技术债 |
| 已确认修复 | 7 | 当前代码或测试已实际落实 |

---

## 2. 对 21 号修复报告的复核

21 号文档列出的提交均存在，测试数量也与实际运行结果一致。但两项关键测试仍使用过度简化的 fake：

- commit 失败测试的 recovery context manager 不模拟真实 SQLAlchemy transaction、锁等待或 commit，只检查 `recovery_config` Python 对象是否被赋值。
- 请求限制测试只提供完整 `http.request` 消息，没有覆盖 `http.disconnect`、永不结束的 `more_body` 或慢速分块。

因此，“33 passed”能够证明已编码的正常测试通过，不能证明恢复事务和 ASGI 生命周期安全。

---

## 3. 必须修复

### 3.1 [必须修复] 客户端断连导致请求体缓冲循环不退出

**位置**：

- `backend/app/sdk_main.py:42-61`
- `backend/app/admin_main.py` 对应缓冲逻辑

当前循环：

```python
more_body = True
while more_body:
    message = await receive()
    if message.get("type") != "http.request":
        chunks.append(message)
        continue
```

当 ASGI server 返回：

```python
{"type": "http.disconnect"}
```

代码进入 `continue`，但 `more_body` 仍为 `True`。如果后续 `receive()` 继续返回 disconnect，循环永远不会终止。

#### 实际探针

让 `receive()` 每次返回 `http.disconnect`，使用 `asyncio.wait_for(..., timeout=0.1)`：

```text
disconnect: timeout
```

第一次未让出事件循环的探针甚至占满循环，使整个 30 秒命令超时，说明在立即完成的 receive 实现下可能形成高 CPU 自旋。

#### 另一处同类问题：超限后等待剩余 body

代码在发现超限后继续执行：

```python
while more_body:
    msg = await receive()
    more_body = msg.get("more_body", False)
```

攻击者可以持续发送 `more_body=True` 的慢速或无限流，使应用始终不返回 413。Nginx 有上游限制可以降低风险，但应用层中间件本身不应等待攻击者完成超限请求。

#### 建议

- 收到 `http.disconnect` 立即返回，不调用下游应用。
- 一旦累计超限，立即发送 413 并返回，不继续排空无限请求体。
- 如果 Uvicorn 需要主动关闭/排空连接，应通过服务器支持的明确机制处理，而不是无界等待。
- 缓冲循环只保存 `http.request` 消息，不要把 disconnect 或 lifespan 等消息加入重放列表。

必须增加：

- body 读取前断连。
- 多个 chunk 中途断连。
- 超限后仍持续 `more_body=True`。
- 慢速分块超时。
- 确认断连不会调用下游端点、不会发送第二套响应。

### 3.2 [必须修复] commit 失败恢复可能自锁，持久化测试不成立

**位置**：

- `backend/app/services/config_service.py:105-122`
- `backend/app/services/config_service.py:171-188`
- `backend/tests/test_reconcile.py:203-235`

当前 commit 失败处理：

```python
except Exception:
    async with async_session_factory() as recovery_session:
        async with recovery_session.begin():
            cfg = await recovery_session.get(SdkConfig, config.id)
            cfg.cos_upload_status = "failed"
    raise HTTPException(...)
```

问题是原 `db` session 没有先执行 `rollback()`。commit 失败后，原事务可能仍持有：

- `pg_try_advisory_xact_lock(9999)`。
- 对 `sdk_configs` 行和唯一索引的锁。
- 失败事务的连接资源。

恢复 session 随即读取和更新同一配置行，可能等待原 session 释放锁。原 session 又要等当前函数抛出异常后，才由 `get_db()` 执行 rollback，因此可能形成等待环：

```text
原函数等待 recovery session 完成
recovery session 等待原事务释放锁
原事务只有函数返回后才 rollback
```

#### 为什么新增测试不能证明持久化

测试中的 `_FakeAsyncContextManager.__aexit__()` 什么也不做，没有 commit；`FakeDbCommitFail` 也不模拟锁。最终断言只是：

```python
assert recovery_config.cos_upload_status == "failed"
```

它证明 Python 假对象被赋值，不证明独立事务提交成功，更不证明不会被原事务锁阻塞。

#### 建议

最低限度应：

1. 捕获 commit 异常后立即 `await db.rollback()`，释放原事务和 advisory lock。
2. 再开启独立 session 写恢复记录。
3. 恢复记录应使用独立表，而不是复用可能仍为 draft/archived 的业务配置行。
4. 恢复写入失败时保留原异常并记录双重故障，不能被第二个异常覆盖。

更可靠的方案仍是 Outbox/发布任务表，在 COS 操作之前持久化发布意图，使 commit 失败后无需依靠同一业务行反推目标版本。

必须使用真实 PostgreSQL 集成测试验证：

- 原事务 commit 失败/rollback 后锁释放。
- recovery session 能在超时范围内写入并提交。
- 失败记录在新 session 中重新查询仍存在。
- advisory lock 可以被后续发布重新获取。

---

## 4. 建议修改

### 4.1 [建议修改] failed 标记没有保存完整目标版本数据

恢复逻辑给原配置行设置 `cos_upload_status='failed'`，并把目标版本拼入 `change_log`。但结构化字段 `version`、`cos_key`、目标 latest 内容和失败阶段没有被可靠保存。

原事务 rollback 后，该配置行仍可能保持旧 draft/archived 版本。后续程序只能解析自由文本 change_log，无法自动恢复。

建议增加独立发布任务表，至少包含：目标版本、配置 ID、COS version key、latest 是否成功、DB 是否成功、失败阶段、重试次数和最后错误。

### 4.2 [建议修改] 对账仍不是定时任务

`docs/TECH-DEBT.md` 已准确记录此问题为 Medium，但 21 号文档的“0 剩余”与技术债本身矛盾。当前只有手工 `/configs/reconcile`，没有周期调用、告警或自动恢复。

建议在上线检查中明确要求外部 cron/监控调用该接口，直至正式任务实现。

### 4.3 [建议修改] latest 缓存穿透参数只有秒级精度

**位置**：`backend/app/api/admin/config_mgr.py:45-46`

同一秒内多次对账会使用相同 `_t` 参数。如果 CDN 缓存键包含 query string，它仍可能命中同一个缓存对象。建议使用纳秒、UUID 或禁用缓存的专用源站读取方式。

同时需要确认腾讯云 CDN 的 query string 缓存键配置；仅设置客户端 `Cache-Control: no-cache` 不保证 CDN 一定回源。

### 4.4 [建议修改] 请求体限制代码在 SDK/Admin 中重复

两套纯 ASGI 中间件逻辑相同，连续多轮修复都需要同步修改两个文件，容易再次出现行为漂移。建议提取到 `app/core/middleware.py`，SDK/Admin 只传不同的 `max_bytes`。

### 4.5 [建议修改] 对账与恢复测试仍偏 mock

当前对账测试 mock 掉整个 `httpx.AsyncClient`，没有断言请求 URL 必须包含 `/config/latest.json`，也没有断言 cache-bust 参数和 no-cache headers。

建议记录 fake client 收到的 URL/headers 并明确断言，另外增加 `httpx.MockTransport` 测试真实响应解析行为。

---

## 5. 已确认修复

### 5.1 超限响应双 body 已消除

中间件在调用下游应用前完成正常超限判断。超过限制时直接发送 413 并返回，不再产生下游解析错误 body。

### 5.2 虚假较小 Content-Length 已无法直接绕过计数

Content-Length 只用于快速拒绝，所有放行请求仍会累计实际接收字节。

### 5.3 对账已读取 latest.json

对账 URL 已改为：

```text
<CDN_BASE_URL>/config/latest.json?_t=<timestamp>
```

不再读取版本化配置对象。

### 5.4 对账数据库条件与 SDK 一致

对账查询同时限制 `status='published'` 和 `cos_upload_status='success'`。

### 5.5 rollback 重复 advisory lock 已去除

锁只在 `rollback_config()` 入口获取，内部 `_publish_from_record()` 明确假定调用方已持锁。

### 5.6 对账路由和异步客户端保持正确

静态 `/configs/reconcile` 位于动态 ID 路由之前，并使用 `httpx.AsyncClient`。

### 5.7 部署迁移包和失败门禁保持正确

部署文档继续同时打包 `backend/ scripts/`，并在重启服务前执行迁移，失败时退出。

---

## 6. 验证记录

### 6.1 后端完整测试

```text
命令：python -m pytest backend/tests -q
结果：33 passed in 8.73s
结论：现有测试全部通过，但未覆盖断连循环和真实数据库锁/持久化
```

21 号文档记录为 8.56 秒，本轮实际复跑为 8.73 秒；测试数量一致，时间差异正常。

### 6.2 前端生产构建

```text
命令：npm run build
结果：构建成功，656 modules transformed
主 JS：约 683.71 kB，gzip 后约 237.20 kB
警告：chunk 超过 500 kB
结论：构建通过
```

### 6.3 客户端断连探针

第一轮 `receive()` 立即持续返回 `http.disconnect`：

```text
外层 shell 命令在 30 秒后超时
```

第二轮让 `receive()` 每次显式 `await asyncio.sleep(0)`，并使用 0.1 秒 wait_for：

```text
disconnect: timeout
```

结论：缓冲循环没有断连终止分支。

### 6.4 commit 恢复语义检查

```text
原 session commit 失败后的显式 rollback：不存在
恢复 session 启动时原事务锁释放证明：不存在
真实数据库集成测试：不存在
测试 recovery context manager commit：未模拟
测试断言：仅检查 fake Python 对象字段
```

### 6.5 未执行的外部验证

本轮没有连接真实 PostgreSQL、腾讯云 COS 或 Nginx，因此尚未验证：

- commit 失败后的真实锁释放与恢复写入。
- COS latest 缓存穿透。
- 对账接口在真实 CDN 上的准确性。
- Nginx 与应用双层断连、慢速分块行为。

---

## 7. 与 20 号报告问题的状态对照

| 20 号报告问题 | 当前状态 | 说明 |
|---|---|---|
| 超限双响应体 | 已修复 | 下游调用前判断超限，不再追加解析错误 body |
| commit failed 不持久化 | 部分修复 | 增加独立 session，但未先 rollback，存在锁等待；测试不证明真实提交 |
| 对账读取版本化对象 | 已修复 | 已改为 latest.json |
| rollback 重复锁 | 已修复 | 内部函数不再重复获取 |
| 对账非定时 | 未修复/已登记技术债 | 手工接口，无周期告警恢复 |
| 发布测试不足 | 部分修复 | 增加 fake commit 测试，真实事务锁测试仍缺失 |

---

## 8. 建议修复顺序

1. 修复中间件对 `http.disconnect` 和超限无限流的处理，并补超时测试。
2. commit 异常后先 rollback 原 session，再使用新事务写独立恢复记录。
3. 使用真实 PostgreSQL 验证锁释放、恢复提交和后续发布。
4. 引入结构化发布任务/Outbox，替代 change_log 恢复标记。
5. 增强 latest 对账 URL、headers 和 CDN 缓存行为测试。
6. 将请求限制中间件提取为公共实现。
7. 接入定时对账和告警。

---

## 9. 上线判定

**当前判定：不建议上线。**

重新评估上线至少需要满足：

- 客户端断连和无限分块不会造成循环、CPU 自旋或请求长期占用。
- commit 失败后原事务明确 rollback，恢复记录能在独立事务真实提交。
- 恢复记录包含足够的结构化数据完成重试或人工修复。
- 真实 PostgreSQL 集成测试证明锁释放和恢复持久化。
- 后端完整测试继续保持 0 failed。
- 完成 PostgreSQL、COS/CDN、Nginx 端到端验证。

