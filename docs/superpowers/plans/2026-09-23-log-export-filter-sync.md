# 日志查看与导出筛选同步实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让 CSV 导出完整复用日志查看页的包名、SDK 版本、设备 ID、日志级别和日期筛选，修复 SDK 版本筛选只影响查看、不影响下载的问题。

**架构：** 前端把当前页面包名和 SDK 版本传给导出面板；后端导出任务持久化可空 `sdk_version`，工作器按任务值精确过滤。页面未选包名时继续使用现有多包选择器，保持批量导出能力。

**技术栈：** Vue 3、TypeScript、Vitest、FastAPI、Pydantic v2、SQLAlchemy 2、PostgreSQL、Pytest。

---

## 文件结构

- 修改 `frontend/src/views/LogViewer.vue`：传递页面包名和 SDK 版本。
- 修改 `frontend/src/components/LogExportPanel.vue`：计算有效包名并发送 SDK 版本。
- 修改 `frontend/src/api/logExports.ts`：扩展请求类型。
- 修改前端测试：锁定查看与导出筛选一致性。
- 修改 `backend/app/schemas/log_export_schemas.py`：接收 SDK 版本。
- 修改 `backend/app/models/log_export_job.py`：持久化任务筛选。
- 修改 `backend/app/services/log_export_service.py`：应用 SDK 版本条件。
- 修改 `scripts/init_db.sql`、`scripts/migrate_log_export_jobs.sql`：兼容新旧数据库。
- 修改后端测试：锁定模型、SQL和迁移。

### 任务 1：后端导出任务支持 SDK 版本

**文件：**
- 修改：`backend/app/schemas/log_export_schemas.py`
- 修改：`backend/app/models/log_export_job.py`
- 修改：`backend/app/services/log_export_service.py`
- 修改：`scripts/init_db.sql`
- 修改：`scripts/migrate_log_export_jobs.sql`
- 测试：`backend/tests/test_log_export_service.py`
- 测试：`backend/tests/test_log_export_api.py`

- [ ] **步骤 1：编写失败测试**

扩展模型列测试，要求 `sdk_version` 存在、可空、长度 20。扩展创建请求/API测试：

```python
body = LogExportCreateRequest(package_names=["com.a"], sdk_version="1.0.6")
assert body.sdk_version == "1.0.6"
```

增加超长 21 字符返回 422 的 API 测试。扩展 SQL 过滤测试：

```python
job.sdk_version = "1.0.6"
assert "sdk_events.sdk_version = '1.0.6'" in compiled_sql
```

另建 `sdk_version=None` 用例，断言 SQL 不含 `sdk_events.sdk_version =`。迁移测试要求初始化 SQL和迁移文件包含字段，且存在 `ADD COLUMN IF NOT EXISTS sdk_version VARCHAR(20)`。

- [ ] **步骤 2：运行红灯**

```powershell
python -m pytest backend/tests/test_log_export_service.py backend/tests/test_log_export_api.py -q
```

预期：请求模型、ORM、过滤 SQL和迁移缺少 `sdk_version` 而失败。

- [ ] **步骤 3：最小实现**

请求和 ORM 增加：

```python
sdk_version: str | None = Field(default=None, max_length=20)
sdk_version = Column(String(20))
```

`apply_job_filters()` 增加：

```python
if job.sdk_version:
    stmt = stmt.where(SdkEvent.sdk_version == job.sdk_version)
```

更新初始化和迁移 SQL；`create_job()` 继续使用现有 `body.model_dump()` 自动持久化字段。

- [ ] **步骤 4：验证并提交**

运行步骤 2、后端全量 `python -m pytest backend/tests -q` 和 `git diff --check`。

```bash
git add backend/app/schemas/log_export_schemas.py backend/app/models/log_export_job.py backend/app/services/log_export_service.py scripts/init_db.sql scripts/migrate_log_export_jobs.sql backend/tests/test_log_export_service.py backend/tests/test_log_export_api.py
git commit -m "fix: apply sdk version to log exports"
```

### 任务 2：前端导出复用查看筛选

**文件：**
- 修改：`frontend/src/views/LogViewer.vue`
- 修改：`frontend/src/components/LogExportPanel.vue`
- 修改：`frontend/src/api/logExports.ts`
- 测试：`frontend/src/components/LogExportPanel.test.ts`
- 测试：`frontend/src/views/LogViewer.test.ts`

- [ ] **步骤 1：编写失败测试**

`LogExportPanel` 使用以下 props：

```ts
{
  packageName: "com.a",
  sdkVersion: "1.0.6",
  deviceId: "d1",
  logLevel: "error",
  dateFrom: "2026-09-01",
  dateTo: "2026-09-23",
}
```

断言请求为：

```ts
{
  package_names: ["com.a"],
  sdk_version: "1.0.6",
  device_id: "d1",
  log_level: "error",
  date_from: "2026-09-01",
  date_to: "2026-09-23",
}
```

断言页面包名非空时不显示 `PackageMultiSelect`，清空时恢复多包选择并使用其值。`LogViewer` 测试断言当前 `rawFilters.package_name` 和 `rawFilters.sdk_version` 传给面板。

- [ ] **步骤 2：运行红灯**

```powershell
npm --prefix frontend test -- --run src/components/LogExportPanel.test.ts src/views/LogViewer.test.ts
```

预期：缺少 props、SDK 版本请求字段和包名同步行为而失败。

- [ ] **步骤 3：最小实现**

扩展请求类型：

```ts
sdk_version?: string;
```

扩展组件 props，并计算：

```ts
const effectivePackageNames = computed(() =>
  props.packageName ? [props.packageName] : packageNames.value,
);
```

按钮禁用和请求均使用 `effectivePackageNames`。页面已选包名时隐藏多选器并显示导出范围文本；请求加入 `sdk_version: props.sdkVersion || undefined`。`LogViewer` 传入两个新 prop。

- [ ] **步骤 4：验证并提交**

运行步骤 2、前端全量测试、`npm --prefix frontend run build` 和 `git diff --check`。

```bash
git add frontend/src/views/LogViewer.vue frontend/src/components/LogExportPanel.vue frontend/src/api/logExports.ts frontend/src/components/LogExportPanel.test.ts frontend/src/views/LogViewer.test.ts
git commit -m "fix: sync log filters with exports"
```

### 任务 3：整体回归与范围审计

**文件：**
- 检查：本计划全部文件
- 修改：仅修复本计划测试发现的缺陷

- [ ] **步骤 1：运行后端全量测试**

```powershell
python -m pytest backend/tests -q
```

- [ ] **步骤 2：运行前端全量和构建**

```powershell
npm --prefix frontend test -- --run
npm --prefix frontend run build
```

- [ ] **步骤 3：执行范围检查**

```powershell
git diff a57abe3934a27b609bd97ca7e86202084af06ed6..HEAD --check
git diff --name-only a57abe3934a27b609bd97ca7e86202084af06ed6..HEAD
```

确认只修改日志导出筛选链路，没有改变 CSV 内容、查看查询、设备元数据分支或其他模块。若验证需要修正，使用 `git add -u` 后提交 `fix: complete log export filter sync`；无修正则不创建空提交。
