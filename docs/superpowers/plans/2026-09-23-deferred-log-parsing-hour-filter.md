# 日志后置解析与小时筛选实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 停止日志上报后的自动解析，改为管理员按包名和连续北京时间范围显式创建解析任务，并让解析统计、原始日志和 CSV 导出统一支持小时筛选，且 10,000 条正常日志端到端解析不超过 60 秒。

**架构：** 原始日志写入只保存 `sdk_events`；Admin API 只负责创建、查询和取消任务；独立 `sdk-log-parse-worker` 复用现有租约和游标表，在最多 3 个进程中解析、由主进程批量写库。所有页面与任务共用一个 UTC+8 半开区间转换函数，查看、明细、导出和解析范围使用同一语义。

**技术栈：** Python 3.11/3.12、FastAPI、Pydantic 2、SQLAlchemy 2 Async、PostgreSQL 16、`ProcessPoolExecutor`、pytest、Vue 3、TypeScript、Axios、Vitest、Vite、systemd。

---

## 文件结构与职责

- 修改 `backend/app/core/timezone.py`：唯一的北京时间日期/小时到 UTC 半开区间转换函数。
- 修改 `backend/app/core/config.py`：解析批量、并发、超时和空闲轮询环境变量。
- 修改 `backend/app/models/log_analysis.py`：扩展统一解析任务模型和状态约束。
- 修改 `backend/app/models/log_export_job.py`：持久化导出开始/结束小时。
- 修改 `backend/app/schemas/log_analysis_schemas.py`：解析任务创建请求、状态响应和严格范围校验。
- 修改 `backend/app/schemas/log_export_schemas.py`：导出小时参数及成对校验。
- 修改 `backend/app/api/sdk/log.py`：只写原始日志，不创建 pending 占位。
- 修改 `backend/app/admin_main.py`：删除 Admin 进程内自动解析和重解析循环。
- 修改 `backend/app/services/log_parse_service.py`：抽取可跨进程传输的纯解析输入/输出和批量持久化函数。
- 修改 `backend/app/services/log_reparse_service.py`：统一 parse/reparse 任务领取、筛选、进度、取消、租约和失败保护。
- 创建 `backend/app/workers/log_parse_worker.py`：独立 worker 入口和进程池生命周期。
- 修改 `backend/app/services/log_analysis_service.py`：任务创建/查询/取消、覆盖率、小时过滤和 SDK 版本过滤。
- 修改 `backend/app/api/admin/log_analysis.py`：任务 API、覆盖率 API、统计和明细小时参数。
- 修改 `backend/app/services/analysis_service.py`、`backend/app/api/admin/dashboard.py`：原始日志小时过滤。
- 修改 `backend/app/services/log_export_service.py`、`backend/app/api/admin/log_exports.py`：导出任务复用相同小时范围。
- 修改 `scripts/init_db.sql`、`scripts/migrate_log_analysis.py`、`scripts/migrate_log_export_jobs.sql`：新安装及生产幂等迁移、约束和索引。
- 创建 `scripts/benchmark_log_parse.py`：10,000 条端到端解析性能门禁，不连接生产业务数据。
- 创建 `scripts/restore_pending_log_placeholders.py`：紧急回滚时只为没有任何解析结果的原始日志恢复旧 pending 占位。
- 创建 `deploy/sdk-log-parse-worker.service.example`：独立 worker 的 systemd 限额。
- 创建 `docs/48-DEFERRED-LOG-PARSING-DEPLOYMENT-20260923.md`：本功能专属迁移、备份、门禁和回滚流程。
- 修改 `frontend/src/api/logAnalysis.ts`、`frontend/src/api/dashboard.ts`、`frontend/src/api/logExports.ts`：小时和任务类型/API。
- 修改 `frontend/src/components/LogAnalysisFilters.vue`：小时、SDK 版本和显式“开始解析”。
- 创建 `frontend/src/components/LogParseJobCard.vue`：任务状态、进度、覆盖率、取消。
- 修改 `frontend/src/components/LogExportPanel.vue`、`frontend/src/views/LogViewer.vue`：应用小时条件并轮询任务。
- 修改对应后端和前端测试文件；不重构无关页面或解析词库。

### 任务 1：统一连续北京时间边界

**文件：**
- 修改：`backend/app/core/timezone.py`
- 修改：`backend/tests/test_timezone.py`

- [ ] **步骤 1：写失败测试**

加入同日、跨日、23 点、缺省全天和非法组合测试，固定接口：

```python
def test_business_hour_range_is_continuous_and_end_hour_inclusive():
    start, end = business_hour_utc_range(date(2026, 9, 20), 8, date(2026, 9, 22), 17)
    assert start.isoformat() == "2026-09-20T00:00:00+00:00"
    assert end.isoformat() == "2026-09-22T10:00:00+00:00"

def test_business_hour_range_defaults_to_full_days():
    start, end = business_hour_utc_range(date(2026, 9, 20), None, date(2026, 9, 20), None)
    assert end - start == timedelta(days=1)

@pytest.mark.parametrize("hours", [(8, None), (None, 17), (-1, 1), (1, 24)])
def test_business_hour_range_rejects_invalid_hours(hours):
    with pytest.raises(ValueError):
        business_hour_utc_range(date(2026, 9, 20), hours[0], date(2026, 9, 20), hours[1])
```

- [ ] **步骤 2：确认红灯**

运行：`python -m pytest backend/tests/test_timezone.py -q`

预期：因 `business_hour_utc_range` 尚不存在而失败。

- [ ] **步骤 3：实现唯一边界函数**

```python
def business_hour_utc_range(date_from, hour_from, date_to, hour_to):
    start_hour = 0 if hour_from is None and hour_to is None else hour_from
    end_hour = 23 if hour_from is None and hour_to is None else hour_to
    if start_hour is None or end_hour is None:
        raise ValueError("hour_from 和 hour_to 必须成对提供")
    if not 0 <= start_hour <= 23 or not 0 <= end_hour <= 23:
        raise ValueError("小时必须在 0 到 23 之间")
    start = datetime.combine(date_from, time(start_hour), BUSINESS_TIMEZONE)
    end = datetime.combine(date_to, time(end_hour), BUSINESS_TIMEZONE) + timedelta(hours=1)
    if end <= start:
        raise ValueError("结束时间必须晚于开始时间")
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)
```

- [ ] **步骤 4：验证并提交**

运行：`python -m pytest backend/tests/test_timezone.py -q`，预期全部通过。

```bash
git add backend/app/core/timezone.py backend/tests/test_timezone.py
git commit -m "feat: add Beijing hour range helper"
```

### 任务 2：扩展任务与导出持久化模型

**文件：**
- 修改：`backend/app/models/log_analysis.py`
- 修改：`backend/app/models/log_export_job.py`
- 修改：`scripts/init_db.sql`
- 修改：`scripts/migrate_log_analysis.py`
- 修改：`scripts/migrate_log_export_jobs.sql`
- 修改：`backend/tests/test_log_analysis_migration.py`
- 修改：`backend/tests/test_log_export_service.py`

- [ ] **步骤 1：写迁移和模型失败测试**

断言 `LogReparseJob` 包含设计文档列、`cancelling` 状态约束和 `job_type` 约束；断言 `LogExportJob` 包含 `hour_from/hour_to`；断言迁移重复执行不生成重复 DDL，并包含：

```sql
CREATE INDEX IF NOT EXISTS idx_events_package_sdk_ts
ON sdk_events (package_name, sdk_version, server_ts DESC);
```

- [ ] **步骤 2：确认红灯**

运行：

```bash
python -m pytest backend/tests/test_log_analysis_migration.py backend/tests/test_log_export_service.py -q
```

预期：缺少列、约束或索引而失败。

- [ ] **步骤 3：实现模型和新安装 DDL**

给 `LogReparseJob` 增加：`job_type`、`sdk_version`、`device_id`、`log_level`、`force_reparse`、`snapshot_end`、`total_count`、`skipped_count`、`batch_size`、`concurrency`、`started_at`、`finished_at`、`last_heartbeat_at`、`cancel_requested_at`；状态集合改为 `pending/running/cancelling/success/failed/cancelled`。给导出任务增加两个可空整数小时列和 0..23 约束。

- [ ] **步骤 4：实现生产幂等迁移**

`migrate_log_analysis.py` 必须先识别现有列和约束，再生成 `ADD COLUMN IF NOT EXISTS`；替换旧状态约束时先把 `succeeded` 归一为 `success`。分区事件表的索引必须在父表创建并由迁移快照验证当前分区可用。`migrate_log_export_jobs.sql` 只追加小时列/约束，不重建表。

- [ ] **步骤 5：验证 dry-run、幂等与提交**

运行步骤 2 命令两次，预期均通过；再运行 `python scripts/migrate_log_analysis.py`，预期只打印计划、不修改数据库。

```bash
git add backend/app/models/log_analysis.py backend/app/models/log_export_job.py scripts/init_db.sql scripts/migrate_log_analysis.py scripts/migrate_log_export_jobs.sql backend/tests/test_log_analysis_migration.py backend/tests/test_log_export_service.py
git commit -m "feat: extend log parse job persistence"
```

### 任务 3：断开日志上报与自动解析

**文件：**
- 修改：`backend/app/api/sdk/log.py`
- 修改：`backend/app/admin_main.py`
- 修改：`backend/tests/test_sdk_api.py`
- 修改：`backend/tests/test_log_parse_service.py`

- [ ] **步骤 1：写失败测试**

测试一次批量上报只执行 `SdkEvent` insert，不引用 `LogDecode`/`DECODER_VERSION`，并断言 Admin lifespan 只启动 ETL，不启动 `pending_log_parse_loop` 或 `reparse_job_loop`。

- [ ] **步骤 2：确认红灯**

运行：`python -m pytest backend/tests/test_sdk_api.py backend/tests/test_log_parse_service.py -q`

预期：当前代码仍创建 pending 且启动两个解析循环。

- [ ] **步骤 3：最小修改**

删除 `pending_values` 和 `pg_insert(LogDecode)`；保留事件 `RETURNING` 完整性检查和原有 accepted/rejected 响应。删除 Admin 中两个循环的 import、函数、task 创建和取消，只保留 ETL 生命周期。

- [ ] **步骤 4：验证并提交**

运行步骤 2，预期通过；额外运行 `python -m pytest backend/tests/test_request_size_limit.py backend/tests/test_rate_limit.py -q`，确认上报保护未退化。

```bash
git add backend/app/api/sdk/log.py backend/app/admin_main.py backend/tests/test_sdk_api.py backend/tests/test_log_parse_service.py
git commit -m "refactor: defer SDK log parsing"
```

### 任务 4：实现统一解析任务 worker

**文件：**
- 修改：`backend/app/core/config.py`
- 修改：`backend/app/services/log_parse_service.py`
- 修改：`backend/app/services/log_reparse_service.py`
- 创建：`backend/app/workers/log_parse_worker.py`
- 修改：`backend/tests/test_settings.py`
- 修改：`backend/tests/test_log_parse_service.py`
- 修改：`backend/tests/test_log_reparse_service.py`

- [ ] **步骤 1：写纯解析和任务失败测试**

覆盖：批量上限 200、并发限制 1..3、`snapshot_end`、SDK/设备/级别精确筛选、跳过当前 decoder 版本、强制覆盖、游标 `(server_ts,id)`、取消、租约续期、连续 10 超时和处理至少 100 条后失败率大于 20%。进程输入只允许可 pickle 的 dataclass/字典，不传 ORM 或 DB session。

- [ ] **步骤 2：确认红灯**

运行：

```bash
python -m pytest backend/tests/test_settings.py backend/tests/test_log_parse_service.py backend/tests/test_log_reparse_service.py -q
```

- [ ] **步骤 3：抽取进程安全解析单元**

定义 `ParseEventInput`（事件键、包名、设备、extra）和 `ParseEventOutput`（状态、values、是否超时），同步函数只调用 `decode_extra` 并投影结果；数据库删除/upsert 仍只在主 worker 执行。保留 `_safe_parse_error` 的脱敏行为。

- [ ] **步骤 4：统一任务查询与批量提交**

`build_reparse_event_query()` 必须把范围限制为 `[range_start, snapshot_end)`，应用 `job_type`、package/sdk/device/level、force/version 和游标；每批最多使用任务固化的 `batch_size`。主 worker 汇总一批输出后，一次删除该批事件旧派生行、一次批量 upsert、同一事务更新游标/计数/心跳。

- [ ] **步骤 5：实现独立 worker 生命周期**

`worker_loop()` 创建一个 `ProcessPoolExecutor(max_workers=settings.LOG_PARSE_CONCURRENCY)`，全局一次只领取一个任务；活跃任务无固定 sleep，无任务 sleep `LOG_PARSE_IDLE_SECONDS`。配置默认值：batch 200、concurrency 3、单条超时 5 秒、idle 1 秒，并在 Settings 校验范围。

- [ ] **步骤 6：验证故障恢复并提交**

运行步骤 2，预期全部通过；测试模拟当前批提交前中断，重新领取后结果幂等且游标不越过未提交批次。

```bash
git add backend/app/core/config.py backend/app/services/log_parse_service.py backend/app/services/log_reparse_service.py backend/app/workers/log_parse_worker.py backend/tests/test_settings.py backend/tests/test_log_parse_service.py backend/tests/test_log_reparse_service.py
git commit -m "feat: add deferred log parse worker"
```

### 任务 5：实现解析任务与覆盖率 API

**文件：**
- 修改：`backend/app/schemas/log_analysis_schemas.py`
- 修改：`backend/app/services/log_analysis_service.py`
- 修改：`backend/app/api/admin/log_analysis.py`
- 修改：`backend/tests/test_log_analysis_service.py`
- 修改：`backend/tests/test_log_analysis_api.py`

- [ ] **步骤 1：写 API 失败测试**

覆盖创建、查询、取消、鉴权、409 单活任务、7 天上限、必填包名/日期/小时、`snapshot_end=min(request_end, now)`、total/skipped、任务不存在 404 和覆盖率按事件键去重。

- [ ] **步骤 2：确认红灯**

运行：`python -m pytest backend/tests/test_log_analysis_service.py backend/tests/test_log_analysis_api.py -q`

- [ ] **步骤 3：定义稳定请求和响应**

创建 `LogParseJobCreateRequest`，必填 `package_name/date_from/hour_from/date_to/hour_to`，可选 `sdk_version/device_id/log_level/force_reparse`。响应统一序列化 `total_count/processed_count/decoded_count/failed_count/skipped_count/status/speed_per_second/eta_seconds`，不返回租约 owner 或原始 extra。

- [ ] **步骤 4：实现四个端点**

```text
POST /api/admin/log-analysis/parse-jobs
GET  /api/admin/log-analysis/parse-jobs/{id}
POST /api/admin/log-analysis/parse-jobs/{id}/cancel
GET  /api/admin/log-analysis/coverage
```

取消 pending 直接变 `cancelled`；取消 running 设 `cancelling/cancel_requested_at`，worker 在当前批提交后结束。保留旧 `/log-analysis/reparse`，内部转换成统一 `job_type=reparse`。

- [ ] **步骤 5：验证并提交**

运行步骤 2，预期通过。

```bash
git add backend/app/schemas/log_analysis_schemas.py backend/app/services/log_analysis_service.py backend/app/api/admin/log_analysis.py backend/tests/test_log_analysis_service.py backend/tests/test_log_analysis_api.py
git commit -m "feat: expose log parse job APIs"
```

### 任务 6：解析统计和明细应用小时、SDK 与覆盖范围

**文件：**
- 修改：`backend/app/services/log_analysis_service.py`
- 修改：`backend/app/api/admin/log_analysis.py`
- 修改：`backend/tests/test_log_analysis_service.py`
- 修改：`backend/tests/test_log_analysis_api.py`

- [ ] **步骤 1：写失败测试**

断言 summary 接收 `hour_from/hour_to/sdk_version`；details 接收全局 `date_from/hour_from/date_to/hour_to/sdk_version`，并把被点击日期与全局连续范围求交集。中间日全天、起始日从开始小时、终止日到结束小时末。

- [ ] **步骤 2：确认红灯**

运行任务 5 的测试命令，预期新参数断言失败。

- [ ] **步骤 3：复用统一时间函数**

删除统计服务自行组合全天边界的分支；所有条件使用 `business_hour_utc_range()` 返回的 UTC `[start,end)`。`sdk_version` 精确匹配 `SdkEvent.sdk_version`。coverage 和 summary 必须 `count(distinct (event_id,event_server_ts))`，避免一个 extra 多行解码重复计数。

- [ ] **步骤 4：验证并提交**

运行任务 5 测试命令，预期通过。

```bash
git add backend/app/services/log_analysis_service.py backend/app/api/admin/log_analysis.py backend/tests/test_log_analysis_service.py backend/tests/test_log_analysis_api.py
git commit -m "feat: filter log analysis by continuous hours"
```

### 任务 7：原始日志查看与导出使用相同小时条件

**文件：**
- 修改：`backend/app/services/analysis_service.py`
- 修改：`backend/app/api/admin/dashboard.py`
- 修改：`backend/app/services/log_export_service.py`
- 修改：`backend/app/api/admin/log_exports.py`
- 修改：`backend/app/schemas/log_export_schemas.py`
- 修改：`backend/tests/test_analysis_service.py`
- 修改：`backend/tests/test_admin_api.py`
- 修改：`backend/tests/test_log_export_service.py`
- 修改：`backend/tests/test_log_export_api.py`

- [ ] **步骤 1：写失败测试**

用同一组输入同时调用事件查询和 `apply_job_filters()`，断言 SQL 参数边界完全一致；小时必须成对出现，未传小时保持全天兼容，跨日是一个连续区间。

- [ ] **步骤 2：确认红灯**

运行：

```bash
python -m pytest backend/tests/test_analysis_service.py backend/tests/test_admin_api.py backend/tests/test_log_export_service.py backend/tests/test_log_export_api.py -q
```

- [ ] **步骤 3：实现查看和导出筛选**

`GET /events` 增加 `hour_from/hour_to`；`LogExportCreateRequest`、模型序列化和导出 SQL 增加相同字段。两条路径只能调用 `business_hour_utc_range()`，禁止 `datetime.combine()` 重复实现。

- [ ] **步骤 4：验证查看/导出一致性并提交**

运行步骤 2，预期通过。

```bash
git add backend/app/services/analysis_service.py backend/app/api/admin/dashboard.py backend/app/services/log_export_service.py backend/app/api/admin/log_exports.py backend/app/schemas/log_export_schemas.py backend/tests/test_analysis_service.py backend/tests/test_admin_api.py backend/tests/test_log_export_service.py backend/tests/test_log_export_api.py
git commit -m "feat: apply hour filters to logs and exports"
```

### 任务 8：实现前端小时筛选和显式解析交互

**文件：**
- 修改：`frontend/src/api/logAnalysis.ts`
- 修改：`frontend/src/api/dashboard.ts`
- 修改：`frontend/src/api/logExports.ts`
- 修改：`frontend/src/components/LogAnalysisFilters.vue`
- 创建：`frontend/src/components/LogParseJobCard.vue`
- 修改：`frontend/src/components/LogExportPanel.vue`
- 修改：`frontend/src/views/LogViewer.vue`
- 修改：`frontend/src/api/logAnalysis.test.ts`
- 修改：`frontend/src/api/dashboard.test.ts`
- 修改：`frontend/src/api/logExports.test.ts`
- 修改：`frontend/src/components/LogAnalysisFilters.test.ts`
- 创建：`frontend/src/components/LogParseJobCard.test.ts`
- 修改：`frontend/src/components/LogExportPanel.test.ts`
- 修改：`frontend/src/views/LogViewer.test.ts`

- [ ] **步骤 1：写 API 类型和组件失败测试**

固定 `hour_from/hour_to` 为数字或 undefined，任务状态包含 `cancelling`；断言“查询结果”只 GET，“开始解析”只 POST 一次；包名、日期和小时不完整时前端阻止创建并显示中文原因。

- [ ] **步骤 2：确认红灯**

工作目录 `frontend`，运行：

```bash
npm test -- --run src/api/logAnalysis.test.ts src/api/dashboard.test.ts src/api/logExports.test.ts src/components/LogAnalysisFilters.test.ts src/components/LogParseJobCard.test.ts src/components/LogExportPanel.test.ts src/views/LogViewer.test.ts
```

- [ ] **步骤 3：扩展筛选值和 API**

`LogAnalysisFilterValues` 增加 `hour_from/hour_to/sdk_version`；小时下拉固定 0..23，显示 `00:00–00:59` 格式。新增 create/get/cancel/coverage API，普通 summary/details/events/export 透传同一 applied filters。

- [ ] **步骤 4：实现任务卡和轮询**

任务卡显示状态、目标、处理、成功、失败、跳过、覆盖率、速度和 ETA；pending/running/cancelling 时每 2 秒查询当前任务，组件卸载或终态立即停止 timer。创建按钮提交时禁用，409 显示当前任务而不重复创建。取消按钮只在允许状态显示。

- [ ] **步骤 5：保证查询、明细和导出一致**

`LogViewer.vue` 区分 draft/applied；分页、刷新、明细和导出只读 applied。任务成功后刷新 coverage 与 summary；失败/取消保留上一次成功数据。原始日志小时字段同时传给 `LogExportPanel`。

- [ ] **步骤 6：验证并提交**

运行步骤 2，预期通过；运行 `npm run build`，预期退出码 0（现有 chunk-size 警告可保留）。

```bash
git add frontend/src/api/logAnalysis.ts frontend/src/api/dashboard.ts frontend/src/api/logExports.ts frontend/src/components/LogAnalysisFilters.vue frontend/src/components/LogParseJobCard.vue frontend/src/components/LogExportPanel.vue frontend/src/views/LogViewer.vue frontend/src/api/logAnalysis.test.ts frontend/src/api/dashboard.test.ts frontend/src/api/logExports.test.ts frontend/src/components/LogAnalysisFilters.test.ts frontend/src/components/LogParseJobCard.test.ts frontend/src/components/LogExportPanel.test.ts frontend/src/views/LogViewer.test.ts
git commit -m "feat: add deferred parsing controls to log viewer"
```

### 任务 9：增加 worker 部署模板和一分钟性能门禁

**文件：**
- 创建：`deploy/sdk-log-parse-worker.service.example`
- 创建：`scripts/benchmark_log_parse.py`
- 创建：`scripts/restore_pending_log_placeholders.py`
- 创建：`backend/tests/test_log_parse_benchmark.py`
- 创建：`backend/tests/test_restore_pending_log_placeholders.py`
- 创建：`docs/48-DEFERRED-LOG-PARSING-DEPLOYMENT-20260923.md`

- [ ] **步骤 1：写配置和基准脚本测试**

测试 service 包含：

```ini
ExecStart=/www/wwwroot/sdk-api/backend/venv/bin/python -m app.workers.log_parse_worker
CPUQuota=300%
MemoryMax=1536M
Nice=5
Restart=always
```

基准脚本必须要求显式测试数据库 URL，拒绝连接包含生产库主机/未带 `--confirm BENCHMARK_LOG_PARSE` 的执行；生成或读取 10,000 条受控样本，计时从建任务到 success，并校验结果事件数。回滚脚本默认 dry-run，只有 `--apply --confirm RESTORE_PENDING_LOGS` 才写库，并使用 `NOT EXISTS` 保证只恢复完全没有 `sdk_log_decodes` 行的日志事件。

- [ ] **步骤 2：确认红灯**

运行：

```bash
python -m pytest backend/tests/test_log_parse_benchmark.py backend/tests/test_restore_pending_log_placeholders.py -q
```

预期：脚本文件缺失而失败。

- [ ] **步骤 3：实现模板和基准**

基准输出 JSON：`total_events/elapsed_seconds/events_per_second/decoded/failed/cpu_peak/memory_peak/pass`；`pass` 仅在 elapsed<=60、failed=0、结果无重复且 worker/API 健康时为 true，失败退出码非 0。

- [ ] **步骤 4：补部署顺序但不执行部署**

专属文档写明：数据库/发布目录/systemd/Nginx 备份；迁移 dry-run；确认旧 pending=0；部署代码；停止 Admin 内旧循环；启用 worker；小范围冒烟；10k 门禁；通过后才投入生产；回滚脚本先 dry-run，再按确认口令重建仅缺少解析结果的 pending 占位。

- [ ] **步骤 5：验证并提交**

运行步骤 2，预期通过；仅在隔离的生产同规格环境运行基准，未达到 60 秒不得把计划标记完成。

```bash
git add deploy/sdk-log-parse-worker.service.example scripts/benchmark_log_parse.py scripts/restore_pending_log_placeholders.py backend/tests/test_log_parse_benchmark.py backend/tests/test_restore_pending_log_placeholders.py docs/48-DEFERRED-LOG-PARSING-DEPLOYMENT-20260923.md
git commit -m "chore: add log parse worker deployment gate"
```

### 任务 10：全量回归、独立审查和交付候选

**文件：**
- 检查：本计划涉及的全部文件
- 不创建无关修复

- [ ] **步骤 1：后端全量验证**

运行：`python -m pytest backend/tests -q`

预期：0 failed；基线为 272 passed，新增测试后通过数应大于 272。

- [ ] **步骤 2：前端全量验证**

工作目录 `frontend`：

```bash
npm test -- --run
npm run build
```

预期：0 failed、构建退出码 0。

- [ ] **步骤 3：迁移和静态检查**

```bash
python scripts/migrate_log_analysis.py
git diff --check
git status --short
```

预期：迁移只列出预期字段/约束/索引；无空白错误；仅存在本功能计划内文件。

- [ ] **步骤 4：独立规格审查**

由独立审查窗口逐条对照 `docs/superpowers/specs/2026-09-23-deferred-log-parsing-hour-filter-design.md`，重点核对：无隐式解析、连续小时语义、查看/导出一致、单活任务、快照、取消、租约、脱敏、7 天限制和 60 秒门禁。审查发现的问题必须回到对应任务用 TDD 修复并重跑全量验证。

- [ ] **步骤 5：形成候选提交，不推送不部署**

```bash
git log --oneline 86a03f3..HEAD
git status --short
```

预期：任务提交清晰、工作树干净。把 commit 列表、测试证据、基准证据和未解决风险交给主会话判断；未经用户明确授权，不推送、合并或部署。

## 执行约束

- 执行窗口固定使用 `gpt-5.6-luna`；当前主会话不写业务代码。
- 每个任务实现后先做规格符合性审查，再做代码质量审查；两者都通过才进入下一任务。
- 执行期间不得修改 `D:\code\SDK` 脏工作区，只使用本计划所在 worktree。
- 不修改解析词库、SDK 请求体、其他页面样式或无关安全问题。
- 60 秒性能基准没有真实通过前，不得宣称功能可生产发布。
- 本计划完成只产生可审查候选；推送、合并和生产部署需要用户再次明确授权。
