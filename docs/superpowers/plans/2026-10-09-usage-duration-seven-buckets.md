# 使用时长七桶实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans（本任务内联执行）。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 为 Admin 使用时长包级汇总提供七个互斥时长桶，并在每桶返回设备数、占比和最新设备总时长秒。

**架构：** 后端沿用 `(package_name, device_id)` 最新记录 window 子查询，在同一包级 SQL 聚合中使用 `sum(case(...))` 计算七桶 count 与 duration sum；API 类型直接暴露七桶。前端保持现有筛选、总/平均/最后上报和按需明细，仅将桶 cell 改为两行/两项信息，不扩展为 21 个表格列。

**技术栈：** Python、FastAPI、SQLAlchemy、PostgreSQL、pytest、Vue 3、TypeScript、Vitest、Vite。

---

### 任务 1：建立七桶红灯测试与更新测试夹具

**文件：**
- 修改：`backend/tests/test_usage_duration_summary.py`
- 修改：`backend/tests/test_log_scope_and_usage_integration.py`
- 修改：`frontend/src/components/UsageDurationPanel.test.ts`
- 修改：`frontend/src/api/usageDurations.test.ts`

- [ ] **步骤 1：编写失败测试**

把服务断言改为七个 key，并为各边界 duration 建立期望的 count、share、`total_duration_s`；增加同 timestamp 以较大 id 胜出的记录、多包和跨机型同设备记录。集成夹具断言一包一行、count 总和等于 device_count、桶总时长等于包总时长。前端 fixture 改为七桶，并断言七个桶 cell 同时显示 count/share 和秒数。

- [ ] **步骤 2：运行测试确认正确失败**

运行：`python -m pytest -q backend/tests/test_usage_duration_summary.py backend/tests/test_log_scope_and_usage_integration.py`

预期：服务测试因仍返回四桶且缺少 `total_duration_s` 失败；失败原因必须是契约缺失而不是导入/语法错误。

- [ ] **步骤 3：提交测试阶段**

```powershell
git add backend/tests/test_usage_duration_summary.py backend/tests/test_log_scope_and_usage_integration.py frontend/src/components/UsageDurationPanel.test.ts frontend/src/api/usageDurations.test.ts
git commit -m "test: specify seven usage duration buckets"
```

### 任务 2：实现后端七桶 SQL 聚合和 API 契约

**文件：**
- 修改：`backend/app/services/usage_duration_service.py`
- 修改：`frontend/src/api/usageDurations.ts`

- [ ] **步骤 1：实现最小后端改动**

集中定义七桶 `(key, predicate, count_column, duration_column)`；在同一个 `grouped` select 中为每桶加入 `sum(case((predicate, 1), else_=0))` 和 `coalesce(sum(case((predicate, duration_s), else_=0)), 0)`，将 count/duration 转为安全整数。`_bucket_items` 按固定顺序读取两列，并用 package `device_count` 计算 share；不改变 latest window 的范围、order by 或包级 group by。

- [ ] **步骤 2：更新 TypeScript 类型**

将 `DurationBucket.key` 改为七个字面量，并增加 `total_duration_s: number`；保留 `UsageSummaryItem` 的总时长、平均时长、最后上报和 `device_model: null` 兼容字段。

- [ ] **步骤 3：运行后端/类型相关测试确认通过**

运行：`python -m pytest -q backend/tests/test_usage_duration_summary.py backend/tests/test_usage_duration_api.py backend/tests/test_usage_duration_admin_api.py`

预期：七桶、排序、分页、鉴权和空结果相关测试全部通过，且 SQL 断言显示没有按 model 分组或选择未聚合 model。

- [ ] **步骤 4：提交后端契约实现**

```powershell
git add backend/app/services/usage_duration_service.py frontend/src/api/usageDurations.ts
git commit -m "feat: expose seven usage duration buckets"
```

### 任务 3：实现前端桶展示

**文件：**
- 修改：`frontend/src/components/UsageDurationPanel.vue`
- 修改：`frontend/src/components/UsageDurationPanel.test.ts`

- [ ] **步骤 1：在绿灯基础上调整模板**

保留七桶 `v-for` 和内部横向滚动；每个 cell 显示 `bucket.count`、`formatShare(bucket.share)` 与 `formatDuration(bucket.total_duration_s)`，使用稳定 `data-testid=usage-bucket-${bucket.key}`。更新 detail 行 `colspan` 为实际表格列数，不改变筛选和按需明细请求。

- [ ] **步骤 2：运行前端定向测试**

运行：`npm --prefix frontend test -- --run src/components/UsageDurationPanel.test.ts src/api/usageDurations.test.ts`

预期：API 请求参数、七桶顺序、总时长格式化和设备明细展开测试通过。

- [ ] **步骤 3：提交前端展示实现**

```powershell
git add frontend/src/components/UsageDurationPanel.vue frontend/src/components/UsageDurationPanel.test.ts
git commit -m "feat: display usage duration bucket totals"
```

### 任务 4：真实 PostgreSQL 集成验证和全量验收

**文件：**
- 修改：`backend/tests/test_log_scope_and_usage_integration.py`（仅在需要时补充边界夹具）
- 创建：`docs/51-LOG-METRICS-USAGE-DURATION-SEVEN-BUCKETS-ACCEPTANCE-20261009.md`

- [ ] **步骤 1：确认本机数据库能力**

仅使用本机 loopback PostgreSQL 临时库/cluster；记录实际 `SELECT version()` 输出。若本机没有 PG14.22，明确记录未验证的版本，不连接生产、不启动未知库、不安装大工具。

- [ ] **步骤 2：运行真实集成测试**

运行：`SDK_LOG_SCOPE_TEST_DATABASE_URL=<loopback sdk_scope_test_...> python -m pytest -q backend/tests/test_log_scope_and_usage_integration.py`

预期：真实 SQL 通过七桶边界、最新 id tie-break、多包/跨机型去重断言；测试库结束后删除专用数据库和角色。

- [ ] **步骤 3：运行完整验证**

运行：`python -m pytest -q backend/tests`、`npm --prefix frontend test -- --run`、`npm --prefix frontend run build`、`git diff --check`。

预期：输出为后端全量 0 failures、前端全量 0 failures、build exit 0、diff check 无输出。

- [ ] **步骤 4：记录 red-green 证据和边界**

验收文档记录 BASE/HEAD SHA、红灯与绿灯命令输出摘要、PG 版本、bucket contract、无生产操作声明和未改变的上传/日期/解析/配置/schema 边界。

- [ ] **步骤 5：提交验收记录**

```powershell
git add docs/51-LOG-METRICS-USAGE-DURATION-SEVEN-BUCKETS-ACCEPTANCE-20261009.md
git commit -m "docs: record seven usage duration bucket acceptance"
```
