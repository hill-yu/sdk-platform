# 事件包名统一与日志 Extra 字符串化实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将事件链路的 `app_id` 全面替换为 `package_name`，并把日志 `extra` 改为必传原始字符串、`message` 改为可空。

**架构：** SDK 请求模型统一复用配置包名规范化函数；事件数据库列、ORM、Admin 查询、分析 SQL 和前端字段同时改名。独立 PostgreSQL 迁移脚本负责无损列重命名、索引和物化视图重建，并提供默认预检与显式确认写入。

**技术栈：** Python 3.11、FastAPI/Pydantic 2、SQLAlchemy Async、PostgreSQL、pytest、Vue 3/TypeScript/Vitest。

---

## 文件结构

- 修改 `backend/app/schemas/sdk_schemas.py`：点击/日志请求使用 `package_name`；日志 extra/message 新规则。
- 修改 `backend/app/api/sdk/click.py`、`log.py`：写入规范化包名和日志原始字符串。
- 修改 `backend/app/models/event.py`：ORM 列改为 `package_name VARCHAR(255)`。
- 修改 `backend/app/api/admin/dashboard.py`、`backend/app/services/analysis_service.py`：Admin 查询和响应改名。
- 修改 `frontend/src/api/dashboard.ts`、`frontend/src/views/Dashboard.vue`：查询参数和显示字段改名。
- 修改 `scripts/init_db.sql`：新建库直接使用 package_name、对应索引和物化视图。
- 创建 `scripts/migrate_event_package_name.py`：生产数据库结构和数据无损迁移。
- 修改/创建后端与前端测试：覆盖新协议、拒绝旧字段和迁移幂等性。
- 修改 `docs/44-COMPLETE-API-INTEGRATION-GUIDE-20260811.md`、`docs/42-PRODUCTION-SYSTEM-API-BASELINE-20260811.md`：更新现行接口。
- 创建 `docs/45-PACKAGE-NAME-LOG-EXTRA-IMPLEMENTATION-20260811.md`：实施记录。

### 任务 1：SDK 请求模型与事件写入

**文件：**
- 修改：`backend/app/schemas/sdk_schemas.py`
- 修改：`backend/app/api/sdk/click.py`
- 修改：`backend/app/api/sdk/log.py`
- 修改：`backend/tests/test_sdk_api.py`

- [ ] **步骤 1：编写失败测试**

增加测试断言：

```python
payload = {
    "package_name": " COM.Example.App ",
    "device_id": "device-1",
    "logs": [{"level": "info", "extra": "{raw|payload}"}],
}
response = client.post("/api/v1/log", json=payload)
assert response.status_code == 200
assert inserted["package_name"] == "com.example.app"
assert inserted["payload"]["message"] == ""
assert inserted["payload"]["extra"] == "{raw|payload}"
```

另测：旧 `app_id`、缺 level、缺 extra、extra 为对象/数组/数字/布尔/null 均返回 422；message 缌失/null/空字符串均成功。点击请求使用 package_name，旧 app_id 返回 422。

- [ ] **步骤 2：运行测试确认失败**

运行：`python -m pytest backend/tests/test_sdk_api.py -q`

预期：新 package_name 请求 422，旧 app_id 仍成功，extra 对象仍被接受。

- [ ] **步骤 3：实现最小请求模型**

为点击和日志请求增加：

```python
package_name: str = Field(..., min_length=1, max_length=255)

@field_validator("package_name")
@classmethod
def validate_package_name(cls, value: str) -> str:
    return normalize_package_name(value)
```

删除 `app_id`。日志条目调整为：

```python
level: str
message: str | None = Field(None, max_length=10000)
extra: str
```

- [ ] **步骤 4：修改写入逻辑**

点击和日志写入使用 `body.package_name`。日志 payload 使用 `"message": log_entry.message or ""` 和 `"extra": log_entry.extra`，不得使用 `or {}`。

- [ ] **步骤 5：运行定点测试并提交**

运行：`python -m pytest backend/tests/test_sdk_api.py -q`；预期全部通过。

```bash
git add backend/app/schemas/sdk_schemas.py backend/app/api/sdk/click.py backend/app/api/sdk/log.py backend/tests/test_sdk_api.py
git commit -m "feat(events): require package name and string log extra"
```

### 任务 2：ORM、Admin、分析和前端统一改名

**文件：**
- 修改：`backend/app/models/event.py`
- 修改：`backend/app/api/admin/dashboard.py`
- 修改：`backend/app/services/analysis_service.py`
- 修改：`backend/tests/test_admin_api.py`
- 修改：`backend/tests/test_analysis_service.py`
- 修改：`frontend/src/api/dashboard.ts`
- 修改：`frontend/src/views/Dashboard.vue`
- 创建：`frontend/src/api/dashboard.test.ts`

- [ ] **步骤 1：编写后端失败测试**

断言 Admin 事件查询使用 `package_name` 参数，响应 item 包含 `package_name` 且不含 `app_id`；分析查询 SQL/ORM 条件引用 `SdkEvent.package_name`。

- [ ] **步骤 2：运行后端定点测试确认失败**

运行：`python -m pytest backend/tests/test_admin_api.py backend/tests/test_analysis_service.py -q`

- [ ] **步骤 3：修改 ORM 和后端查询**

将 `SdkEvent.app_id` 改为：

```python
package_name = Column(String(255), nullable=False)
```

Admin 参数、service 签名、where 条件、序列化字段和日志脱敏上下文统一改为 package_name。

- [ ] **步骤 4：编写并运行前端失败测试**

在 `frontend/src/api/dashboard.test.ts` 测试请求查询参数为 `package_name`；同时核对 `Dashboard.vue` 的筛选变量、占位文案和请求参数均不再使用 app_id。先运行 `npm test -- --run` 确认旧实现失败。

- [ ] **步骤 5：修改前端并验证**

更新 TypeScript 类型、API 参数、筛选模型、表头和字段绑定。运行后端定点测试与 `npm test -- --run`，预期全部通过。

- [ ] **步骤 6：提交全链路改名**

```bash
git add backend/app/models/event.py backend/app/api/admin/dashboard.py backend/app/services/analysis_service.py backend/tests frontend/src
git commit -m "refactor(events): use package name across event queries"
```

### 任务 3：数据库初始化和无损迁移

**文件：**
- 修改：`scripts/init_db.sql`
- 创建：`scripts/migrate_event_package_name.py`
- 创建：`backend/tests/test_event_package_migration.py`

- [ ] **步骤 1：编写迁移失败测试**

覆盖：旧结构生成重命名操作；新结构预检返回 changes=0；事件总数不一致时抛错；DROP/CREATE 物化视图和索引顺序正确；正式执行缺确认串时拒绝。

- [ ] **步骤 2：运行测试确认模块不存在**

运行：`python -m pytest backend/tests/test_event_package_migration.py -q`

- [ ] **步骤 3：实现预检与 SQL 计划**

通过 `information_schema.columns` 检测列状态。旧结构计划包括：

```sql
ALTER TABLE sdk_events RENAME COLUMN app_id TO package_name;
ALTER TABLE sdk_events ALTER COLUMN package_name TYPE VARCHAR(255);
DROP INDEX IF EXISTS idx_events_app;
CREATE INDEX IF NOT EXISTS idx_events_package ON sdk_events(package_name, server_ts DESC);
```

重建 `mv_daily_event_stats` 及其唯一索引，SELECT/GROUP BY 使用 package_name。记录迁移前后总数、各分区数和 package_name 非空数。

- [ ] **步骤 4：实现 CLI 安全门槛**

```text
python scripts/migrate_event_package_name.py
python scripts/migrate_event_package_name.py --apply --confirm MIGRATE_EVENT_PACKAGE_NAME
```

默认预检；apply 必须确认串；全部 DDL 和验证处于单事务。

- [ ] **步骤 5：更新 init_db.sql 并运行测试**

新库定义只出现 package_name。运行迁移测试及数据库相关测试，预期通过。

- [ ] **步骤 6：提交迁移**

```bash
git add scripts/init_db.sql scripts/migrate_event_package_name.py backend/tests/test_event_package_migration.py
git commit -m "feat(events): migrate event package name column"
```

### 任务 4：残留扫描和现行文档

**文件：**
- 修改：`docs/42-PRODUCTION-SYSTEM-API-BASELINE-20260811.md`
- 修改：`docs/44-COMPLETE-API-INTEGRATION-GUIDE-20260811.md`
- 创建：`docs/45-PACKAGE-NAME-LOG-EXTRA-IMPLEMENTATION-20260811.md`

- [ ] **步骤 1：扫描运行源码残留**

运行：

```powershell
rg -n "\bapp_id\b" backend/app frontend/src scripts tests backend/tests
```

预期：当前运行代码、初始化/迁移和测试不存在业务字段 app_id；迁移脚本检测旧列的字符串和历史迁移测试可作为明确例外。

- [ ] **步骤 2：更新现行文档**

点击、日志、Admin 事件和 Dashboard 文档统一使用 package_name；日志 extra 示例必须是字符串，并说明不解析；message 标记可空。历史审阅报告不修改。

- [ ] **步骤 3：形成实施记录并提交**

记录红绿测试、数据库迁移命令、回滚流程和本地验证，不记录 Token 或数据库密码。

```bash
git add docs/42-PRODUCTION-SYSTEM-API-BASELINE-20260811.md docs/44-COMPLETE-API-INTEGRATION-GUIDE-20260811.md docs/45-PACKAGE-NAME-LOG-EXTRA-IMPLEMENTATION-20260811.md
git commit -m "docs: update package name event integration"
```

### 任务 5：全量验证和本地启用

**文件：**
- 不新增生产源码；将结果追加到实施记录。

- [ ] **步骤 1：后端全量测试**

运行：`python -m pytest backend/tests -q`；预期 0 failed。

- [ ] **步骤 2：前端测试和构建**

工作目录 `frontend`：运行 `npm test -- --run` 和 `npm run build`；预期全部通过且构建退出码 0。

- [ ] **步骤 3：迁移本地数据库**

先运行预检，再备份本地数据库，然后停止本地 SDK/Admin 服务，使用显式确认执行迁移。重复预检必须显示 changes=0。

- [ ] **步骤 4：重启本地服务**

启动 SDK API 8100、Admin API 8101 和前端 5173，验证健康检查和 OpenAPI。

- [ ] **步骤 5：本地冒烟**

验证：新点击和日志请求 200；旧 app_id 422；日志 extra 对象 422；message 三种空值均 200；Admin 按 package_name 查询并返回 package_name；Dashboard 返回 200。

- [ ] **步骤 6：提交验证记录**

更新实施记录，提交脱敏结果。生产部署不在本计划自动执行范围内，等待用户明确要求。
