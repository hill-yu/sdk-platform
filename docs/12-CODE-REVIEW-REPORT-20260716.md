# SDK 数据中台项目代码审阅报告

> 审阅日期：2026-07-16  
> 审阅基线：当前工作区代码  
> 参考文档：`09-CHECKLIST-DEPLOY.md`、`10-ARCHITECTURE-OVERVIEW.md`、`11-REVIEW-CHECKLIST.md`  
> 审阅范围：`backend/app`、`backend/tests`、`frontend/src`、`scripts` 及关键工程配置

---

## 1. 审阅结论

项目整体架构方向合理，SDK API 与 Admin API 进程隔离，后端采用 API → Service → Model 分层，配置通过 COS/CDN 分发，事件数据使用 PostgreSQL 月度分区，主体实现与架构文档基本一致。

但当前代码不满足上线条件。审阅确认存在 5 项必须修复问题，其中包括配置回滚未实际上传 COS、请求体限制未生效、物化视图刷新锁可能泄漏，以及配置发布过程中数据库与 CDN 状态不一致。现有后端测试基线也处于失败状态。

因此，`11-REVIEW-CHECKLIST.md` 中“53/65 项通过，12 项改善均为 Low、不影响上线”的结论需要重新评估。

### 1.1 风险汇总

| 级别 | 数量 | 结论 |
|---|---:|---|
| 必须修复 | 5 | 修复并验证前不建议上线 |
| 建议修改 | 5 | 建议在本次上线前完成安全与稳定性加固 |
| 仅供参考 | 3 | 不阻断上线，可进入后续迭代 |

---

## 2. 架构符合性

### 2.1 符合项

- SDK API 与 Admin API 分别运行于 8100、8101 端口，入口和进程相互隔离。
- 后端目录按 `core`、`models`、`schemas`、`api`、`services` 分层，职责总体清晰。
- SDK 配置接口只返回版本和 CDN 元信息，不直接返回完整配置。
- `sdk_events` 使用 PostgreSQL 按月分区，原始事件通过 JSONB 保存扩展字段。
- SQL 查询主要使用 SQLAlchemy ORM 或 `text()` 参数绑定，未发现用户输入直接拼接 SQL。
- Admin Token 使用 `hmac.compare_digest()` 比较，并在服务启动阶段检查弱 Token。
- 事件字段统一使用 `element`，与项目约定一致。
- 未引入 Redis、ClickHouse、Kafka 等超出当前规模需求的组件。

### 2.2 架构偏差

- 文档声明 SDK 1 MB、Admin 5 MB 请求限制，但代码没有真正实现限制。
- 文档声明 COS 失败可回滚数据库，但没有覆盖 COS 成功、数据库提交失败的反向不一致场景。
- 文档将 advisory lock 视为完整并发保护，但当前实现没有异常安全地释放 session 级锁。
- 回滚发布代码没有真正执行 COS 上传，破坏配置发布主链路。

---

## 3. 必须修复

### 3.1 [必须修复] 配置回滚未实际执行 COS 上传

**位置**：`backend/app/services/config_service.py:165`

```python
_upload_config_payload(cos_key, publish_data)
```

`_upload_config_payload()` 被定义为异步函数，但调用处缺少 `await`。调用只会创建 coroutine 对象，不会执行函数体。接口随后返回成功，数据库事务也会提交，但 COS/CDN 中的配置不会发生变化。

**影响**：

- 管理后台显示“回滚成功”，SDK 继续获取旧配置。
- 数据库记录与 CDN 实际内容不一致。
- 测试运行产生 `coroutine was never awaited` 警告。

**建议**：

- 短期修复为 `await _upload_config_payload(...)`。
- COS SDK 是同步客户端，建议进一步将上传函数改为普通同步函数，并通过 `await asyncio.to_thread(...)` 执行，避免阻塞事件循环。
- 增加断言 COS 两个对象均被上传的回归测试。

### 3.2 [必须修复] SDK/Admin 请求体大小限制未生效

**位置**：

- `backend/app/sdk_main.py:8`
- `backend/app/admin_main.py:74`

```python
FastAPI(..., request_max_size=1_000_000)
```

`request_max_size` 不是 FastAPI 的请求体限制参数。运行时探针确认该值只保存在 `app.extra`，SDK 应用没有相关中间件。

**影响**：

- `11-REVIEW-CHECKLIST.md` 的 E9 实际不通过。
- 无鉴权 `/click` 和 `/log` 接口可接收超大请求，存在内存消耗和拒绝服务风险。
- Admin 配置接口的 5 MB 限制同样不存在。

**建议**：

- Nginx 层分别配置 `client_max_body_size`。
- 应用层增加 ASGI 请求体限制中间件，并对超限请求返回 HTTP 413。
- 增加 1 MB/5 MB 边界测试，验证限制真实生效。

### 3.3 [必须修复] 物化视图刷新锁在异常路径可能永久泄漏

**位置**：`scripts/init_db.sql:147-156`

当前函数获取 `pg_try_advisory_lock(12345)` 后，只有两个刷新均成功才执行 `pg_advisory_unlock(12345)`。任一刷新语句失败都会跳过解锁。

**影响**：

- session 级锁可能随连接返回连接池继续存在。
- 后续 ETL 调度无法获得锁，物化视图长期停止刷新。
- 服务仍然运行，问题不容易通过健康检查发现。

**建议**：

- 优先改用事务级 `pg_try_advisory_xact_lock()`，让事务结束自动释放。
- 或在 PL/pgSQL 异常处理块中确保执行解锁后再抛出异常。
- 增加刷新时间和最后成功时间监控。

### 3.4 [必须修复] 配置发布无法保证数据库与 CDN 一致

**位置**：`backend/app/services/config_service.py:82-131`

代码在数据库 `flush()` 后上传 COS，上传完成后依赖 FastAPI 数据库依赖统一提交。`flush()` 并不等于提交；如果 COS 上传成功而最终数据库提交失败，CDN 已经切换到新配置，数据库仍保留旧状态。

**影响**：

- `/config/meta` 返回的版本可能与 `latest.json` 不一致。
- 管理后台无法准确反映 SDK 实际使用的配置。
- 单纯执行数据库 rollback 无法撤销外部 COS 操作。

**建议**：

采用明确的发布状态机和补偿流程：

1. 数据库记录进入 `publishing` 状态并提交。
2. 上传带版本号的不可变配置对象。
3. 数据库记录版本对象上传成功。
4. 切换 `latest.json`。
5. 数据库记录进入 `published` 状态。
6. 任一步骤失败时记录 `failed`，支持幂等重试和人工恢复。

### 3.5 [必须修复] 后端测试基线失败

**验证命令**：

```powershell
python -m pytest backend/tests -q
```

**结果**：10 failed，7 passed，1 warning。

主要原因：

- Admin API 测试使用的 Token 包含 `admin`、`change-me`，与启动强度校验冲突。
- SDK 写入测试桩仍模拟逐条 `add()`，生产代码已经改为批量 `execute()`。
- 回滚测试要求保留原版本号，而当前实现生成新版本号，需求与实现不一致。
- COS 上传测试暴露异步函数漏 `await`。

**影响**：

- `scripts/deploy.sh` 会运行后端测试，因此当前部署流程会直接失败。
- 无法依赖现有测试证明 SDK 上报、配置发布和 Admin API 正确。

**建议**：

- 为测试环境注入满足强度要求的固定 Token。
- 更新数据库测试桩，使其覆盖批量 `execute()`、commit 和 rollback。
- 明确回滚时是否生成新版本号，并统一实现、API 文档和测试。
- 修复以上问题后重新运行完整测试，要求 0 failed。

---

## 4. 建议修改

### 4.1 [建议修改] 同步 COS 调用阻塞异步事件循环

**位置**：`backend/app/services/config_service.py:103-117、190-203`

腾讯云 COS 客户端的 `put_object()` 是同步网络调用，直接在异步请求函数中执行。上传延迟会阻塞同一 worker 的其他 Admin 请求和健康检查。

建议通过 `asyncio.to_thread()` 执行，或将发布操作交给独立任务进程。

### 4.2 [建议修改] 配置 500 KB 校验检查的是字典键数量

**位置**：`backend/app/schemas/admin_schemas.py:9`

```python
config_data: dict[str, Any] = Field(..., max_length=500000)
```

对字典使用 `max_length` 只限制顶层键数量，不限制序列化 JSON 的字节数。少量键即可携带远超 500 KB 的嵌套数据。

建议在 Pydantic validator 中对 UTF-8 JSON 序列化结果执行字节长度校验。

### 4.3 [建议修改] 配置版本号秒级精度导致唯一键冲突

**位置**：

- `backend/app/services/config_service.py:49`
- `backend/app/services/config_service.py:79、145`

同一秒内创建两个草稿或执行两次发布会生成相同版本号，并触发数据库唯一约束，最终表现为 500。

建议使用数据库序列、UUID，或至少加入微秒/随机后缀。

### 4.4 [建议修改] 生产环境可能返回占位 CDN 地址

**位置**：

- `backend/app/core/config.py:28`
- `backend/app/api/sdk/config.py:54`
- `scripts/init_db.sql:212-213`

当发布记录没有 `cdn_url` 时，接口会静默返回 `cdn.example.com`。这会把部署配置错误转化为 SDK 侧下载失败。

建议在生产启动阶段强制校验 COS/CDN 配置；已发布记录缺少有效 CDN 地址时返回明确服务错误，不要回退到占位域名。

### 4.5 [建议修改] Admin Token 暴露于浏览器持久存储或静态产物

**位置**：`frontend/src/api/request.ts:9`

前端从 `localStorage` 或 `VITE_ADMIN_TOKEN` 读取长期 Token。前者可被 XSS 读取，后者会直接编译进静态 JavaScript。

建议生产构建禁止使用 `VITE_ADMIN_TOKEN`。长期方案应使用登录换取短期会话，通过 `HttpOnly`、`Secure` Cookie 保存凭据。

---

## 5. 仅供参考

### 5.1 [仅供参考] 前端包体较大

前端构建成功，但主 JavaScript 文件约 683 KB，Vite 给出超过 500 KB 的警告。可使用路由懒加载、ECharts 按需引入或 manual chunks 降低首屏体积。

### 5.2 [仅供参考] 临时 Token 文件未被忽略

`backend/token_tmp.txt` 当前是未跟踪文件，且不在 `.gitignore` 中。建议删除临时凭据文件，并增加 `backend/token*.txt` 等忽略规则，防止未来误提交真实 Token。

### 5.3 [仅供参考] Dashboard 参数校验仍可加强

以下项目与 11 号清单记录一致：

- `range`、`dimension` 可使用 `Literal` 或 Enum 约束。
- `/events` 应校验 `date_from <= date_to`。
- `ClickEvent.type` 可根据业务定义限制枚举值。

---

## 6. 对 11 号 Review 清单的复核

| 清单项 | 原结论 | 复核结论 | 原因 |
|---|---|---|---|
| D1/D2 COS 失败回滚 DB | ✅ | ⚠️ | 只覆盖 COS 失败；未覆盖 COS 成功、DB commit 失败；回滚路径还漏了 `await` |
| D5 物化视图并发锁 | ✅ | ❌ | 异常路径可能不释放 session 级锁 |
| E9 请求体大小限制 | ✅ | ❌ | `request_max_size` 不是有效 FastAPI 限制配置 |
| E10 `config_data` 大小限制 | ✅ | ❌ | 限制的是字典键数量，不是 JSON 字节数 |
| C1/COS 异常处理 | ✅ | ⚠️ | 回滚上传 coroutine 未执行，异常处理路径也不会运行 |
| G1 并发发布 last-writer-wins | ✅ | ⚠️ | 秒级版本号可能先触发唯一键冲突；外部 COS 与 DB 也不能实现真正 last-writer-wins |
| H7 CDN fallback 非占位符 | 部署确认 | ❌ | 代码和初始 SQL 仍包含 `example.com` fallback |

---

## 7. 验证记录

### 7.1 后端测试

```text
命令：python -m pytest backend/tests -q
结果：10 failed, 7 passed, 1 warning
结论：失败
```

### 7.2 前端构建

```text
命令：npm run build
结果：构建成功，656 modules transformed
警告：主 JS chunk 约 682.96 kB，超过 500 kB
结论：通过，但存在包体警告
```

### 7.3 请求限制运行时探针

```text
SDK app.extra: {'request_max_size': 1000000}
Admin app.extra: {'request_max_size': 5000000}
SDK middleware: []
Admin middleware: ['CORSMiddleware']
```

结论：请求大小值只是 FastAPI 扩展字段，没有形成实际限制。

---

## 8. 建议修复顺序

1. 修复配置回滚漏 `await`，增加 COS 上传回归测试。
2. 实现真实的 SDK/Admin 请求体限制并验证 HTTP 413。
3. 修复物化视图 advisory lock 异常释放问题。
4. 重构配置发布状态机，补齐 DB/COS 一致性与幂等机制。
5. 恢复后端测试基线，确保部署脚本测试全部通过。
6. 修正配置字节大小校验和秒级版本号冲突。
7. 移除生产占位地址和前端构建时 Token。
8. 优化同步 COS 调用、前端包体和其他低优先级输入校验。

---

## 9. 上线判定

**当前判定：不建议上线。**

至少需要满足以下条件后重新评估：

- 5 项“必须修复”全部关闭。
- 后端完整测试为 0 failed。
- 前端生产构建通过。
- 使用超限请求验证 SDK 1 MB、Admin 5 MB 限制真实生效。
- 在测试 COS 环境完成“新建草稿 → 发布 → 回滚 → SDK 获取元信息 → 下载 latest.json”的端到端验证。
- 人工制造 ETL 刷新失败后，确认 advisory lock 能释放并在下一周期恢复刷新。

