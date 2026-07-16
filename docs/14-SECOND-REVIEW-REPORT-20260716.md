# SDK 数据中台二次代码审阅报告

> 审阅日期：2026-07-16  
> 审阅对象：根据 `12-CODE-REVIEW-REPORT-20260716.md` 实施修复后的当前工作区代码  
> 参考文档：`10-ARCHITECTURE-OVERVIEW.md`、`11-REVIEW-CHECKLIST.md`、`12-CODE-REVIEW-REPORT-20260716.md`、`13-REVIEW-FEEDBACK.md`  
> 审阅范围：后端应用、数据库初始化脚本、后端测试、前端鉴权处理及部署配置

---

## 1. 二次审阅结论

本轮修改已经解决第一次审阅发现的多项问题，包括配置回滚漏执行上传、同步 COS 调用阻塞事件循环、advisory lock 异常泄漏、配置 JSON 字节限制、秒级版本号冲突以及测试基线失败。

但是，当前实现仍存在 3 项上线阻断问题：

1. COS 上传失败的配置仍保持 `published`，并会被 SDK 元信息接口选中。
2. 新增 `cos_upload_status` 字段没有提供现有数据库迁移。
3. 请求体限制只检查 `Content-Length`，分块请求可以绕过，非法头部会触发 500。

因此，虽然当前后端测试为 17/17 通过、前端构建成功，项目仍不建议上线。测试全绿只能证明现有用例通过，尚未覆盖上述三条关键风险路径。

### 1.1 风险汇总

| 级别 | 数量 | 结论 |
|---|---:|---|
| 必须修复 | 3 | 上线前必须关闭 |
| 建议修改 | 4 | 建议随阻断项一并处理 |
| 已确认修复 | 8 | 代码已落地并完成相应静态或运行验证 |

---

## 2. 对 13 号文档的说明

`13-REVIEW-FEEDBACK.md` 的正文主要是对第一次审阅意见的分析、接受情况和后续修复计划，文末也写明“接下来逐项修复”。它不是一份包含代码位置、变更记录和验证输出的完整修复报告。

本次二次审阅没有直接采信 13 号文档中的“认同”或“修复方案”，而是逐项检查了当前代码，并运行测试、前端构建和请求体限制探针。本文中的结论均以代码事实和实际命令输出为准。

---

## 3. 必须修复

### 3.1 [必须修复] COS 上传失败的配置仍对 SDK 可见

**位置**：

- `backend/app/services/config_service.py:83-118`
- `backend/app/services/config_service.py:145-177`
- `backend/app/api/sdk/config.py:31-33`

当前发布流程在 COS 上传前执行以下操作：

```python
config.status = "published"
config.cos_upload_status = "pending"
await db.flush()
await db.commit()
```

随后才上传 COS。上传失败时，只将：

```python
config.cos_upload_status = "failed"
```

但配置的 `status` 仍然是 `published`。SDK 元信息接口又只查询：

```python
select(SdkConfig).where(SdkConfig.status == "published")
```

没有要求 `cos_upload_status == "success"`。

#### 影响

- 原有 published 配置先被归档。
- 新配置在上传期间就会被 SDK 元信息接口识别为已发布。
- COS 上传失败后，失败配置仍长期保持 published。
- SDK 可能获得新版本号和版本化 CDN 地址，但 `latest.json` 仍是旧内容。
- 数据库与 SDK 实际下载内容持续不一致。

#### 建议

建议采用以下任一方案：

**方案 A：明确状态机（推荐）**

1. 新记录进入 `publishing`。
2. 上传不可变版本文件。
3. 更新 `latest.json`。
4. COS 全部成功后，在同一数据库事务中归档旧版本并将新版本设为 `published`。
5. 上传失败则记录 `failed`，不影响旧 published 配置。

**方案 B：最小改动**

- SDK 查询同时要求 `status='published' AND cos_upload_status='success'`。
- 上传失败时恢复旧 published 配置。
- 新配置上传成功之前，不归档旧配置。

仅增加 SDK 的 `cos_upload_status='success'` 条件还不够，因为当前流程会提前归档旧配置，上传期间可能出现没有可用配置的窗口。

### 3.2 [必须修复] 新增数据库字段缺少现有环境迁移

**位置**：

- `backend/app/models/config.py:19`
- `scripts/init_db.sql:66-84`

本轮新增：

```sql
cos_upload_status VARCHAR(20) NOT NULL DEFAULT 'pending'
```

但仓库没有 Alembic revision，也没有独立的 `ALTER TABLE` 升级脚本。`CREATE TABLE IF NOT EXISTS sdk_configs` 只对全新数据库有效，不会给已经存在的表增加新列。

#### 影响

部署到已有数据库后，ORM 会尝试查询 `sdk_configs.cos_upload_status`。数据库中没有该列时，配置列表、详情、发布等接口会直接失败。

#### 建议迁移

```sql
ALTER TABLE sdk_configs
ADD COLUMN IF NOT EXISTS cos_upload_status VARCHAR(20);

UPDATE sdk_configs
SET cos_upload_status = CASE
    WHEN status = 'published' THEN 'success'
    ELSE 'pending'
END
WHERE cos_upload_status IS NULL;

ALTER TABLE sdk_configs
ALTER COLUMN cos_upload_status SET DEFAULT 'pending',
ALTER COLUMN cos_upload_status SET NOT NULL;

ALTER TABLE sdk_configs
ADD CONSTRAINT chk_configs_cos_upload_status
CHECK (cos_upload_status IN ('pending', 'success', 'failed'));
```

建议通过 Alembic 管理迁移，并在测试数据库先执行升级和回滚验证。

### 3.3 [必须修复] 请求体限制仍可绕过

**位置**：

- `backend/app/sdk_main.py:11-23`
- `backend/app/admin_main.py:20-32`
- `docs/07-DEPLOYMENT.md:162-195`

当前中间件只检查请求头：

```python
content_length = request.headers.get("content-length")
if content_length and int(content_length) > self.max_bytes:
    return JSONResponse(status_code=413, ...)
```

#### 实际探针结果

在最大限制设置为 10 字节时：

```text
带 Content-Length 的 11 字节请求：413
无 Content-Length 的 12 字节分块请求：200，实际读取 12 字节
Content-Length: invalid：500 Internal Server Error
```

#### 影响

- HTTP 分块传输或没有 `Content-Length` 的请求可以绕过限制。
- 非法 `Content-Length` 会触发未处理的 `ValueError`，返回 500。
- 07 号部署文档中的 Nginx 配置没有落地 13 号文档提出的 `client_max_body_size`。
- 当前测试中没有请求体限制用例。

#### 建议

- 在 ASGI `receive` 层累计实际读取字节数，超限立即返回 HTTP 413。
- 对非法或负数 `Content-Length` 返回 HTTP 400。
- Nginx SDK 路由增加 `client_max_body_size 1m;`。
- Nginx Admin 路由增加 `client_max_body_size 5m;`。
- 增加普通请求、边界值、分块请求、缺失头部和非法头部测试。

---

## 4. 建议修改

### 4.1 [建议修改] Service 和数据库依赖混合管理事务

**位置**：`backend/app/services/config_service.py:94-121、157-175`

Service 在 COS 上传前自行执行一次 `commit()`；上传成功后只执行 `flush()`，再依赖外层 `get_db()` 执行第二次 commit。失败路径则又在 Service 内 commit 失败状态。

这种事务边界分散在 Service 和 FastAPI dependency 两层，后续维护时容易产生重复提交或遗漏提交。

建议统一选择：

- Service 完整管理发布事务，接口使用不自动提交的会话；或
- Service 不直接 commit，全部由上层事务编排器控制。

配置发布涉及外部系统，推荐由独立发布用例统一编排每个事务阶段。

### 4.2 [建议修改] Admin API 未暴露 COS 上传状态

**位置**：`backend/app/services/config_service.py:213-228`

`_serialize_config()` 没有返回 `cos_upload_status`。数据库即使记录了 `failed`，管理后台也无法显示失败状态。

13 号文档提到“支持重试”，但当前代码没有重试接口、任务或管理后台操作。因此目前完成的是“数据库记录失败”，还没有形成可恢复机制。

建议：

- API 返回 `cos_upload_status`。
- 前端明确显示 pending/failed/success。
- 增加仅允许失败记录执行的幂等重试接口。
- 记录最后错误、重试次数和最后重试时间。

### 4.3 [建议修改] 测试桩会吞掉模拟写入异常

**位置**：`backend/tests/conftest.py:63-80`

`StubWriteSession.execute()` 中的：

```python
except Exception:
    pass
```

会把 SQL 编译错误和 `fail_predicate` 主动抛出的模拟写入错误一起吞掉。测试无法可靠模拟数据库批量写入失败，因此“全部拒绝”异常路径仍缺乏有效保障。

建议只捕获参数提取所需的特定异常，模拟写入失败必须向生产函数传播。

### 4.4 [建议修改] 上传状态缺少数据库合法值约束

**位置**：`scripts/init_db.sql:75`

`cos_upload_status` 当前可以写入任意字符串。建议增加：

```sql
CHECK (cos_upload_status IN ('pending', 'success', 'failed'))
```

如果采用正式状态机，应将合法状态集合与业务状态定义统一维护。

---

## 5. 已确认修复

### 5.1 配置回滚漏执行上传

`_upload_config_payload()` 已改为同步函数，调用方通过 `await asyncio.to_thread(...)` 执行。原先未 await coroutine 的问题已经消除。

### 5.2 同步 COS 调用阻塞事件循环

发布和回滚路径已通过 `asyncio.to_thread()` 执行 COS 网络调用，不再直接阻塞 Admin API 事件循环。

### 5.3 advisory lock 异常泄漏

`scripts/init_db.sql` 已改为 `pg_try_advisory_xact_lock(12345)`。事务结束后锁会自动释放，避免连接池持有 session 级锁。

### 5.4 配置 JSON 大小校验

`ConfigUpsertRequest` 已对 UTF-8 JSON 序列化后的字节数执行 500,000 字节限制，不再误把字典键数量当作文件大小。

### 5.5 秒级版本号冲突

草稿和发布版本号已加入微秒后缀，大幅降低同一秒内唯一键冲突概率。

### 5.6 占位 CDN 地址处理

Admin API 启动时会拒绝包含 `example.com` 的 CDN 配置；SDK 元信息接口在 `cdn_url` 缺失时返回明确错误，不再静默回退到占位地址。

### 5.7 前端 Token 处理

前端已移除 `VITE_ADMIN_TOKEN` 和 `localStorage`，改用用户输入和 `sessionStorage`。这降低了 Token 被编译进静态资源或长期持久化的风险，但仍不是完整登录认证方案。

### 5.8 测试基线

原有 10 项失败已经处理，当前完整后端测试为 17/17 通过。

---

## 6. 验证记录

### 6.1 后端测试

```text
命令：python -m pytest backend/tests -q
结果：17 passed in 0.48s
结论：现有测试全部通过
```

需要注意：现有测试没有覆盖 COS 失败后的 SDK 可见性、数据库升级和请求体分块绕过场景。

### 6.2 前端构建

```text
命令：npm run build
结果：构建成功，656 modules transformed
主 JS：约 683.07 kB，gzip 后约 236.97 kB
结论：构建通过，仍有大包警告
```

### 6.3 请求体限制探针

```text
declared oversized: 413
missing length oversized: 200 {'size': 12}
invalid length: 500 Internal Server Error
```

结论：声明了正确 `Content-Length` 的超限请求会被拦截，但无长度分块请求可以绕过，非法长度头部会产生 500。

### 6.4 数据库迁移检查

仓库中没有发现与 `cos_upload_status` 对应的 Alembic revision、migration 文件或独立 `ALTER TABLE` 升级脚本。

### 6.5 未完成验证

本轮没有执行以下外部环境验证：

- 在真实 PostgreSQL 现有库上执行升级。
- 真实 COS 上传成功、版本对象成功但 latest 失败、完全失败等场景。
- Nginx 实际限流。
- SDK 获取元信息后下载 `latest.json` 的端到端一致性。

---

## 7. 与第一次审阅问题的状态对照

| 第一次审阅问题 | 当前状态 | 说明 |
|---|---|---|
| 回滚发布漏 await | 已修复 | 同步上传函数 + `asyncio.to_thread()` |
| 请求体限制无效 | 部分修复 | 普通 Content-Length 超限可拦截，但分块可绕过，Nginx 未配置 |
| advisory lock 泄漏 | 已修复 | 改为事务级锁 |
| COS/DB 一致性 | 未完全修复 | 新增失败标记，但失败配置仍为 published 并对 SDK 可见 |
| 后端测试基线失败 | 已修复 | 17/17 通过，但关键新路径缺少测试 |
| 同步 COS 阻塞 | 已修复 | 已使用线程执行 |
| JSON 大小校验错误 | 已修复 | 按 UTF-8 字节校验 |
| 秒级版本号冲突 | 已修复 | 增加微秒 |
| 占位 CDN fallback | 基本修复 | Admin 启动校验 + SDK 明确报错 |
| 前端长期 Token | 部分改善 | 改为 sessionStorage，完整认证仍待后续实现 |

---

## 8. 建议修复顺序

1. 重构配置发布顺序，确保 COS 失败配置不会替代旧 published 配置。
2. 增加 `cos_upload_status` 数据库迁移和约束。
3. 实现按实际接收字节计数的请求体限制，并补充 Nginx 配置。
4. 为以上三项增加针对性测试。
5. 统一配置发布事务边界。
6. 向 Admin API/前端暴露上传状态并实现幂等重试。
7. 修复测试桩吞异常问题，增加数据库失败覆盖。
8. 在真实 PostgreSQL 与测试 COS 环境执行端到端验证。

---

## 9. 上线判定

**当前判定：不建议上线。**

重新评估上线至少需要满足：

- COS 上传失败时旧 published 配置继续可用，新失败配置不会被 SDK 选中。
- 现有数据库可以通过正式迁移获得 `cos_upload_status`，已有数据完成正确回填。
- SDK 1 MB、Admin 5 MB 限制对普通请求和分块请求均生效。
- 非法 `Content-Length` 返回受控的 400，而不是 500。
- 后端完整测试继续保持 0 failed，并新增上述风险路径用例。
- 完成真实 PostgreSQL、COS/CDN 和 SDK 元信息下载的端到端验证。

