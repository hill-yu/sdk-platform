# SDK 数据中台第四次代码审阅报告

> 审阅日期：2026-07-16  
> 审阅对象：根据 `16-THIRD-REVIEW-REPORT-20260716.md` 和 `17-THIRD-REVIEW-FEEDBACK.md` 修改后的当前代码  
> 审阅范围：请求体限制、配置发布与回滚一致性、对账接口、数据库迁移、部署流程、测试和前端构建  
> 审阅方法：代码逐项复核、完整测试、前端构建、原始 ASGI 请求探针、路由匹配探针

---

## 1. 审阅结论

本轮修改已经将请求体限制重写为纯 ASGI 中间件，分块超限请求能够返回 413；数据库迁移增加了重复执行保护并接入部署文档；初始配置改为 draft；后端测试从 17 项增加到 27 项。

但是，复审发现当前实现仍存在 3 项必须修复问题：

1. 请求体中间件信任较小的 `Content-Length`，声明长度与实际长度不一致时可以绕过限制。
2. 发布锁没有覆盖回滚路径，且 COS latest 成功后数据库提交失败仍无法补偿。
3. 新增的 `/configs/reconcile` 对账接口被 `/configs/{config_id}` 动态路由遮蔽，实际不可访问。

此外，部署更新包没有包含 `scripts/`，即使文档增加了迁移命令，服务器也可能拿不到新增迁移文件；所谓“定期对账”当前只是一个同步阻塞、只读且不可达的手工接口。

因此，虽然当前后端测试为 27/27 通过、前端构建成功，仍不建议直接上线。

### 1.1 风险汇总

| 级别 | 数量 | 上线影响 |
|---|---:|---|
| 必须修复 | 3 | 修复并验证前不建议上线 |
| 建议修改 | 5 | 建议上线前处理或明确进入技术债清单 |
| 已确认修复 | 6 | 当前实现已通过代码和运行验证 |

---

## 2. 对 17 号反馈文档的复核

`17-THIRD-REVIEW-FEEDBACK.md` 提出的纯 ASGI 中间件、发布锁、重试、对账、迁移保护和测试扩充均有代码落地。但部分完成声明只覆盖了正常或单一失败场景：

- 纯 ASGI 中间件解决了无 Content-Length 分块超限，却跳过了合法但虚假的 Content-Length。
- advisory lock 只加在 publish，没有加在 rollback。
- COS 重试只能处理 COS 调用失败，不能处理 COS 成功后的数据库 commit 失败。
- “定期对账”没有定时任务，现有手工接口还被路由遮蔽。
- 新增了请求限制测试，但没有新增发布失败、提交失败和并发测试。

本报告以当前代码与运行结果为准，不以反馈文档中的“修复”字样作为关闭依据。

---

## 3. 必须修复

### 3.1 [必须修复] 较小的 Content-Length 可绕过实际请求体限制

**位置**：

- `backend/app/sdk_main.py:24-41`
- `backend/app/admin_main.py:33-50`

当前中间件在 Content-Length 合法且不超过限制时直接调用下游应用：

```python
if cl is not None:
    ...
    await self.app(scope, receive, send)
    return
```

这意味着它只验证声明长度，不再累计实际接收字节。如果客户端、反向代理或 ASGI 上游传入的声明长度小于实际 body，应用层限制将被绕过。

#### 实际探针

限制 10 字节，ASGI scope 声明 `Content-Length: 1`，实际发送 11 字节：

```text
lying-content-length: 200 {"size":11}
```

预期结果应为 413。

#### 影响

- 应用层 SDK 1 MB、Admin 5 MB 限制不是基于真实接收数据。
- 安全性依赖 Nginx/Uvicorn 是否拒绝长度不一致请求，而中间件自身无法兑现“实际字节限制”的设计目标。
- 当前 10 个新增限流测试没有覆盖该场景。

#### 建议

Content-Length 只能用于提前拒绝明显超限请求，不能作为跳过实际计数的依据。所有被放行的 HTTP 请求都应包装 `receive` 并累计实际字节数。

建议增加：

- Content-Length 小于实际 body 的测试。
- Content-Length 大于实际 body 的行为测试。
- 重复 Content-Length、Transfer-Encoding 与 Content-Length 同时存在的测试。
- 边界值恰好等于限制和超出 1 字节的测试。

### 3.2 [必须修复] 发布互斥没有覆盖回滚，跨系统提交失败仍未补偿

**位置**：

- `backend/app/services/config_service.py:75-112`
- `backend/app/services/config_service.py:115-152`

`publish_config()` 获取了：

```sql
SELECT pg_try_advisory_xact_lock(9999)
```

但 `rollback_config()` 和 `_publish_from_record()` 没有获取同一把锁。以下操作仍可并发：

- publish 与 rollback。
- 两次 rollback。

这些请求都能覆盖 `config/latest.json` 并修改数据库 published 状态，因此仍存在 DB published 与 CDN latest 不一致的竞态。

此外，即使 publish 路径串行执行，当前顺序仍是：

1. 上传版本文件。
2. 覆盖 latest.json。
3. 修改数据库对象。
4. 接口返回后由 `get_db()` commit。

如果第 2 步成功而第 4 步数据库提交失败，latest 已经切换，数据库仍保留旧 published。COS 重试不会处理这种情况，因为 COS 操作本身已经成功。

#### 建议

- 将发布和回滚统一进入同一个发布编排函数，并在任何 COS 操作之前获取同一把事务级锁。
- 为数据库 commit 失败设计明确补偿或持久化重试状态。
- 不要把接口返回前的日志“配置发布完成”视为完成；真正完成点应包括数据库 commit。
- 增加 publish/rollback 并发测试和 commit 失败测试。
- 对账任务必须能发现并触发恢复，而不仅是返回比较结果。

### 3.3 [必须修复] 对账接口被动态路由遮蔽，实际不可访问

**位置**：`backend/app/api/admin/config_mgr.py:26、74`

路由注册顺序为：

```python
@router.get("/configs/{config_id}")
...
@router.get("/configs/reconcile")
```

Starlette 按注册顺序匹配。访问 `/api/admin/configs/reconcile` 时，首先完整匹配 `/configs/{config_id}`，随后因为 `config_id` 不能解析为整数而返回 422，不会继续匹配静态对账路由。

#### 路由匹配探针

```text
first-reconcile-match: /api/admin/configs/{config_id} get_config_detail
```

#### 建议

- 将 `/configs/reconcile` 注册在 `/configs/{config_id}` 之前；或
- 改为不会与 ID 路由冲突的路径，例如 `/config-reconciliation/status`。
- 增加带鉴权的实际 HTTP 测试，验证返回 200 和对账响应结构。

---

## 4. 建议修改

### 4.1 [建议修改] 部署更新包没有包含迁移脚本

**位置**：`docs/07-DEPLOYMENT.md:297-313`

代码更新流程使用：

```bash
tar -czf backend.tar.gz backend/
```

但迁移文件位于 `scripts/migrate_cos_upload_status.sql`。随后服务器执行 `../scripts/migrate_cos_upload_status.sql`，新迁移脚本并未包含在更新包中。

如果服务器原本没有该文件，迁移命令会失败；如果存在旧文件，则可能执行旧版本。

建议更新包同时包含 `backend/` 和 `scripts/`，并用版本化构建产物或 Git commit 标识保证代码与迁移来自同一版本。

### 4.2 [建议修改] 对账不是定时任务，也没有恢复能力

**位置**：`backend/app/api/admin/config_mgr.py:74-110`

17 号反馈提出“定期任务比较 DB 和 COS”，当前实现只是手工 GET 接口：

- 没有调度器或周期任务调用。
- 不一致时只返回 `consistent=false`，不重试、不修复、不告警。
- CDN 拉取失败时返回 `consistent=null`，仅写 warning 日志。

建议至少将对账纳入定时任务和监控告警；如果暂不自动修复，应提供明确的人工恢复步骤和幂等重试接口。

### 4.3 [建议修改] 对账接口在异步路由中执行同步网络 I/O

**位置**：`backend/app/api/admin/config_mgr.py:86-99`

接口直接调用 `urllib.request.urlopen(..., timeout=5)`。该同步调用会阻塞 Admin API 事件循环最长约 5 秒。

建议使用 `httpx.AsyncClient`，或通过 `asyncio.to_thread()` 执行同步请求。

### 4.4 [建议修改] 对账查询未限制上传成功状态

**位置**：`backend/app/api/admin/config_mgr.py:78-81`

数据库侧只查询 `status='published'`，没有同时要求 `cos_upload_status='success'`。虽然正常流程会写 success，但异常或人工数据可能导致对账基准不一致。

建议与 SDK 元信息查询使用相同条件，并复用一个“当前有效配置”查询函数。

### 4.5 [建议修改] 发布失败与并发测试仍未增加

**位置**：`backend/tests/test_config_service.py`

本轮新增的 `test_request_size_limit.py` 覆盖了普通、分块、非法和负数 Content-Length，但 `test_config_service.py` 仍只有一个回滚成功测试。

17 号反馈声明“加请求体限制测试和发布失败测试”，其中发布失败测试没有落地。仍缺少：

- 版本文件上传失败。
- latest.json 上传失败。
- 重试次数耗尽。
- advisory lock 获取失败返回 409。
- 数据库 update/commit 失败。
- publish 与 rollback 并发。
- 两次 rollback 并发。
- 对账一致、不一致和 CDN 不可用。

---

## 5. 已确认修复

### 5.1 无 Content-Length 的分块超限请求返回 413

中间件已改为纯 ASGI 实现，并在无 Content-Length 时先缓存和累计请求体。SDK 和 Admin 的直接 ASGI 分块测试均通过。

### 5.2 非法和负数 Content-Length 返回 400

运行测试确认非法字符串与负数 Content-Length 均返回受控的 HTTP 400。

### 5.3 请求限制测试已增加

新增 `backend/tests/test_request_size_limit.py`，覆盖 SDK/Admin 正常请求、声明超限、无 Content-Length 分块超限、非法长度和负数长度。

### 5.4 迁移约束增加重复执行保护

`migrate_cos_upload_status.sql` 已通过查询 `pg_constraint` 保护 CHECK 约束创建，解决了约束重复添加失败问题。

### 5.5 部署流程增加迁移失败门禁

部署文档已经在重启服务前执行迁移，并在命令失败时退出，方向正确；仍需修复更新包不包含 scripts 的问题。

### 5.6 初始配置改为 draft

`init_db.sql` 的模板记录已改为 `draft/pending`，并明确要求部署后通过管理后台编辑和正式发布，不再伪装为可用 published 配置。

### 5.7 Admin/前端上传状态展示继续保留

配置序列化和前端同步状态标签仍然存在，本轮没有发现对应回归。

---

## 6. 验证记录

### 6.1 后端完整测试

```text
命令：python -m pytest backend/tests -q
结果：27 passed in 4.55s
结论：现有测试全部通过
```

### 6.2 前端生产构建

```text
命令：npm run build
结果：构建成功，656 modules transformed
主 JS：约 683.71 kB，gzip 后约 237.20 kB
警告：chunk 超过 500 kB
结论：构建通过，包体警告不阻断本轮功能
```

### 6.3 虚假 Content-Length 探针

```text
限制：10 字节
声明 Content-Length：1
实际 body：11 字节
结果：200 {"size":11}
预期：413
```

### 6.4 对账路由匹配探针

```text
请求路径：/api/admin/configs/reconcile
第一个完整匹配：/api/admin/configs/{config_id}
处理函数：get_config_detail
```

结论：静态对账接口被动态路由遮蔽。

### 6.5 未执行的外部验证

本轮没有连接真实 PostgreSQL、腾讯云 COS 或 Nginx，因此尚未验证：

- advisory lock 在真实并发事务中的行为。
- COS 三次重试和真实错误类型。
- COS latest 成功后数据库 commit 失败的补偿。
- 迁移在现有数据库上的执行。
- Nginx 对分块和长度不一致请求的处理。
- 对账任务和 CDN 缓存绕过行为。

---

## 7. 与 16 号报告问题的状态对照

| 16 号报告问题 | 当前状态 | 说明 |
|---|---|---|
| 分块超限返回 500 | 部分修复 | 无 Content-Length 分块已返回 413，但虚假较小 Content-Length 可绕过 |
| DB/CDN 一致性与并发 | 部分修复 | publish 已加锁和重试；rollback 未加锁，commit 失败未补偿 |
| 迁移不可重复执行 | 已修复 | CHECK 约束增加存在性检查 |
| 部署流程缺迁移 | 部分修复 | 文档增加执行步骤，但更新包未包含 scripts |
| 初始 published/pending 冲突 | 已修复 | 初始模板改为 draft/pending |
| 关键测试缺失 | 部分修复 | 增加 10 个请求限制测试；发布失败、并发、对账测试仍缺失 |

---

## 8. 建议修复顺序

1. 对所有请求累计实际 body，修复虚假 Content-Length 绕过并补测试。
2. 让 publish 和 rollback 共用同一发布锁与编排逻辑。
3. 为 COS 成功、数据库 commit 失败实现补偿或持久化恢复状态。
4. 调整对账路由顺序并增加真实 HTTP 测试。
5. 将 scripts 纳入部署更新包，验证迁移实际可执行。
6. 将对账改为非阻塞定时任务，接入告警和恢复操作。
7. 增加发布失败、并发、数据库失败和对账测试。
8. 在测试 PostgreSQL、COS 和 Nginx 环境完成端到端验证。

---

## 9. 上线判定

**当前判定：不建议上线。**

重新评估上线至少需要满足：

- 请求限制按实际读取字节工作，虚假 Content-Length 无法绕过。
- publish 和 rollback 均被同一互斥机制保护。
- COS latest 成功后数据库提交失败有可验证的补偿或恢复机制。
- 对账接口可访问，并具备定时执行或明确告警能力。
- 部署包包含并执行对应版本迁移。
- 新增发布失败、并发、迁移和对账回归测试。
- 后端完整测试继续保持 0 failed。
- 完成 PostgreSQL、COS/CDN、Nginx 端到端验证。

