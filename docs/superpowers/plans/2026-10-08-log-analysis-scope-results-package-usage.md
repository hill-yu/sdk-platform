# 日志分析生效范围、正式结果与包级在线时长实施计划

> **目标：** 统一 analysis 的合法 draft、精确 UTC 半开范围、最近任务状态和正式 H1/click 展示；移除旧 `LogDecode` summary 主 UI；usage 保持独立 31 天/空包名规则并按包名一行汇总。
> **基线：** `d08718c7bc0877415eaf04d871a1b5878154a6c2`
> **分支：** `codex/log-analysis-scope-package-usage-20261008`
> **当前状态：** 仅为审查用 spec/plan；本轮不写业务代码、不运行生产任务、不部署。
> **实现原则：** 不做正式结果版本化，不增加正式表 `job_id`，不修改旧 summary/details API，不创建数据库迁移。

## 0. 执行边界与完成定义

### 0.1 保护范围

- 保留用户已有的 `docs/50-LOG-METRICS-DEVICE-DURATION-H1-EXPORT-IMPLEMENTATION-20260930.md` 脏改动，不 stage、不覆盖。
- 不修改分区维护、SDK 上传协议、原始事件写入、配置系统和旧 8102。
- 不删除 `LogDecode`、历史正式 H1/click、usage 历史报告或旧 summary/details API。
- 不创建生产 parse job，不回填生产数据，不执行部署。

### 0.2 实现完成定义

- [ ] analysis query/refresh/parse 统一使用当前合法 draft；usage 继续独立、空包名查全部、最多 31 天。
- [ ] formal metrics 和创建 parse job 共享后端 7 个北京时间自然日校验。
- [ ] `LogViewer.vue` 不再渲染旧 `LogDecode` summary/details 表；不增加兼容面板。
- [ ] 包资料和可配指标在 `LogMetricsPanel.vue` 正式结果界面保留，且有独立生命周期测试。
- [ ] exact scope 最近任务状态按 `(package_name, range_start_utc, range_end_utc)`、`created_at DESC, id DESC` 查询。
- [ ] pending/running、failed/cancelled、all-failed、no-H1、true-zero、no-source、success-nonzero 可区分。
- [ ] formal metrics 只在当前查询范围和合法 snapshot 上限读取，不宣称 job 级不可变结果。
- [ ] usage 一包一行，保留 nullable `device_model` 兼容字段，四个桶边界和上报 1–3600 约束不变。
- [ ] 真实 PostgreSQL 回归已执行；若没有隔离 PG16，验收记录明确写“未验证”，不能用编译代替。

## 1. 先锁定范围契约和审查回归

### 文件

- 新增：`backend/app/services/log_analysis_scope.py`
- 新增：`backend/tests/test_log_analysis_scope.py`
- 新增：`frontend/src/utils/logAnalysisScope.ts`
- 新增：`frontend/src/utils/logAnalysisScope.test.ts`
- 修改：`frontend/src/components/LogAnalysisFilters.vue`
- 修改：`frontend/src/views/LogViewer.vue`
- 修改：`frontend/src/api/logMetrics.ts`
- 修改：`backend/app/schemas/log_metrics_schemas.py`
- 修改：`backend/app/api/admin/log_metrics.py`
- 修改：`backend/app/services/log_parse_job_service.py`
- 修改：`backend/app/services/log_metrics_service.py`
- 测试：`frontend/src/components/LogAnalysisFilters.test.ts`
- 测试：`frontend/src/views/LogViewer.test.ts`
- 测试：`frontend/src/api/logMetrics.test.ts`
- 测试：`backend/tests/test_log_metrics_api_v2.py`
- 测试：`backend/tests/test_log_parse_job_service_v2.py`
- 测试：`backend/tests/test_log_metrics_service_v2.py`

### 步骤

- [ ] **1.1 建立 `AnalysisScope` 后端唯一校验器**

  在 `backend/app/services/log_analysis_scope.py` 定义规范化结果：

  ```text
  package_name
  range_start_utc
  range_end_utc
  ```

  输入可以是现有日期/小时字段；输出必须是 `package_name + UTC 半开完整边界`。统一处理包名规范化、小时边界、正向区间和日期差最多 6 天。`LogParseJobCreateRequest`、`log_metrics.py` 的 metrics scope dependency、最近任务查询和 service 层均调用它。

  不把 usage 的可空包名或 31 天规则放进此 helper。

- [ ] **1.2 固定前端 draft/applied 状态**

  `LogViewer.vue` 只保留一个 `appliedAnalysisScope` 作为 analysis 请求来源。`queryAnalysis(value)`、`refreshAnalysis(value)`、`resetAnalysis(value)` 先应用完整快照，再触发任务状态和 formal metrics 加载。不要从旧 `appliedFilters`、旧 `metricScope` 或闭包重建范围。

  `frontend/src/utils/logAnalysisScope.ts` 只负责默认最近 3 个北京时间自然日、前端合法性校验和显示 scope 到 exact UTC scope 的转换；不发请求、不创建任务。

- [ ] **1.3 保持 usage 独立**

  analysis 的 7 天校验不得复用于 `UsageDurationPanel.vue`。usage 仍允许空包名查全部，日期范围仍由 `usage_duration_service.resolve_usage_summary_range` 校验最多 31 天。

- [ ] **1.4 先写失败/边界测试**

  必须先锁定：

  - 最近 3 天按北京时间自然日；
  - 7 个自然日合法，第 8 个日历日非法；
  - analysis formal metrics 和创建任务都拒绝同一组非法范围；
  - 刷新使用当前完整 draft；
  - 页面挂载、刷新、查询、轮询、指标加载均不 POST parse job；
  - usage 空包名和 31 天规则不受影响。

## 2. 增加 exact scope 最近任务状态查询

### 文件

- 修改：`backend/app/services/log_parse_job_service.py`
- 修改：`backend/app/api/admin/log_metrics.py`
- 修改：`backend/app/schemas/log_metrics_schemas.py`
- 修改：`frontend/src/api/logMetrics.ts`
- 修改：`frontend/src/components/LogParseTaskPanel.vue`
- 修改：`frontend/src/views/LogViewer.vue`
- 修改：`frontend/src/components/LogMetricsPanel.vue`
- 测试：`backend/tests/test_log_parse_job_service_v2.py`
- 测试：`backend/tests/test_log_metrics_api_v2.py`
- 测试：`frontend/src/api/logMetrics.test.ts`
- 测试：`frontend/src/components/LogParseTaskPanel.test.ts`
- 测试：`frontend/src/views/LogViewer.test.ts`

### 步骤

- [ ] **2.1 实现 exact scope 查询 service 和 endpoint**

  新增最近任务查询，例如 `GET /api/admin/log-analysis/parse-jobs/latest`。HTTP 可接收页面的日期/小时输入，但必须经共享 helper 转换后按以下 exact tuple 查询：

  ```text
  package_name = exact package
  range_start = exact UTC start
  range_end = exact UTC end
  ORDER BY created_at DESC, id DESC
  LIMIT 1
  ```

  无匹配返回 `200 { code: 0, data: null }`；不得按日期、包名或 overlap 模糊取任务。

- [ ] **2.2 修正 `ParseJob` 类型与时间输出**

  `frontend/src/api/logMetrics.ts` 的 `ParseJob` 移除 `extends LogMetricScope`。保留 job 自身的 ID、状态、进度和时间字段，增加明确的 `scope.package_name`、`scope.range_start_utc`、`scope.range_end_utc`、`snapshot_end_utc`。

  后端 `serialize_parse_job` 增加/明确 UTC ISO 字段；旧字段若保留，写明其时区。前端通过现有时间格式化工具转换北京时间，不假定响应含 `date_from/hour_from/date_to/hour_to`。

- [ ] **2.3 处理最新任务状态和过期完成事件**

  `LogViewer.vue` 保存当前 exact scope、最新任务和请求序列号。任务 POST/轮询完成后，只有当任务 scope 等于当前 `appliedAnalysisScope` 时才刷新；旧 scope 的完成事件不得覆盖新 scope。

  最新任务为 pending/running 时显示进度；failed/cancelled 时显示错误/取消信息，不能把旧正式数据标成此次成功。

## 3. formal metrics 的 snapshot 查询和失败语义

### 文件

- 修改：`backend/app/services/log_metrics_service.py`
- 修改：`backend/app/api/admin/log_metrics.py`
- 修改：`backend/app/schemas/log_metrics_schemas.py`
- 修改：`frontend/src/api/logMetrics.ts`
- 修改：`frontend/src/components/LogMetricsPanel.vue`
- 修改：`frontend/src/views/LogViewer.vue`
- 测试：`backend/tests/test_log_metrics_service_v2.py`
- 测试：`backend/tests/test_log_metrics_api_v2.py`
- 测试：`frontend/src/components/LogMetricsPanel.test.ts`
- 测试：`frontend/src/views/LogViewer.test.ts`

### 步骤

- [ ] **3.1 增加 snapshot 上限参数和校验**

  formal metrics 请求携带当前 exact scope；当最新任务成功时额外携带 `snapshot_end_utc`。后端验证：

  ```text
  range_start_utc <= snapshot_end_utc <= range_end_utc
  ```

  所有 H1/click 查询使用 `[range_start_utc, min(range_end_utc, snapshot_end_utc))`。若没有成功任务，主 UI 不请求或不展示 formal metrics；不使用旧成功任务冒充当前失败/运行任务。

- [ ] **3.2 保持共享正式表语义**

  不给正式 H1/click 表增加 `job_id`，不做结果版本化。测试和文案明确：重叠任务可以重写相同正式表范围，formal metrics 仅是当前共享正式表在查询 scope/snapshot 上限内的结果，不是 job 级不可变快照。

- [ ] **3.3 排除失败 H1 的成功指标**

  `LogMetricsService` 的 overview、计划、配置分布、计划不一致等成功指标只使用成功 H1；失败 H1 计入失败计数并在 H1 明细/失败区展示脱敏错误。click failure 仍按 `navigation_code IS DISTINCT FROM 1` 计入失败指标。

- [ ] **3.4 固定结果状态矩阵**

  后端/前端测试分别覆盖：

  - `no_source`：任务成功、`total_count=0`；
  - `no_h1`：有源事件但没有成功 H1；
  - `all_failed_h1`：有 H1 但全部失败；
  - `true_zero`：有成功 H1，但正式计划/实际/成功指标确实为 0；
  - `success_nonzero`：至少一个正式指标非零。

  页面不得把这些情况统一成“暂无指标”或全 0。

## 4. 移除旧 LogDecode 主 UI，保留正式界面的必要功能

### 文件

- 修改：`frontend/src/views/LogViewer.vue`
- 修改：`frontend/src/components/LogMetricsPanel.vue`
- 修改：`frontend/src/components/LogColumnSettings.vue`（仅在正式指标 ID 需要调整时）
- 修改：`frontend/src/components/PackageProfileCell.vue`（仅在正式面板 props/lifecycle 需要调整时）
- 修改：`backend/app/services/log_analysis_service.py`（仅列配置目录/兼容适配；不改 summary/details 查询）
- 保留不改：`backend/app/api/admin/log_analysis.py` 的 summary/details 路由
- 保留不改：`frontend/src/api/logAnalysis.ts` 的 summary/details API 类型和函数
- 测试：`frontend/src/views/LogViewer.test.ts`
- 测试：`frontend/src/components/LogMetricsPanel.test.ts`
- 测试：`frontend/src/components/PackageProfileCell.test.ts`
- 测试：`frontend/src/components/LogColumnSettings.test.ts`
- 测试：`frontend/src/api/logAnalysis.test.ts`
- 测试：`backend/tests/test_log_analysis_service.py`

### 步骤

- [ ] **4.1 删除旧分析表和旧详情调用**

  从 `LogViewer.vue` 移除 `getLogAnalysisSummary`、`getLogAnalysisDetails`、`getLogAnalysisDetail` 的 analysis 主页面调用、旧表、旧排序分页、旧 `LogAnalysisDetail` 和旧 `LogDecode` 类型状态。不得新增折叠兼容表。

  后端 summary/details API 不改，外部调用方兼容性不在本次 UI 变更中承担。

- [ ] **4.2 将包资料放到正式结果标题区域**

  `LogMetricsPanel.vue` 正式结果标题区域渲染 `PackageProfileCell` 的 alias/company/account。`LogViewer.vue` 在 applied package 变化时调用既有 `getPackageProfile`，用请求序列号防止旧包响应覆盖新包；保存由 `PackageProfileCell` 调用既有 PUT，成功只更新本地正式面板资料，不创建任务、不刷新旧 summary。

- [ ] **4.3 将可配指标放到正式结果界面**

  `LogViewer.vue` 继续拥有列配置加载/保存和 modal 生命周期，但入口移动到 `LogMetricsPanel.vue` 正式结果标题区域；`LogColumnSettings.vue` 的当前配置驱动 formal metric cards/tables，不再驱动已删除的 LogDecode 表。

  如现有 `log_analysis_service.py` 的列目录仍是旧 summary 字段，只调整 columns preference 的目录/兼容适配，不修改 summary/details SQL/API；已有 JSON preference 以兼容方式读取，用户保存成功后才更新 formal metric 配置，不做数据库迁移。

- [ ] **4.4 测试生命周期**

  覆盖包资料加载、包切换防旧响应、保存成功/失败、范围刷新不触发解析、配置加载/保存失败和正式面板渲染配置后的结果。增加断言：`LogViewer.vue` 不再出现旧 summary/details API 调用或旧表测试选择器。

## 5. usage 包级一行和兼容参数

### 文件

- 修改：`backend/app/services/usage_duration_service.py`
- 修改：`backend/app/api/admin/usage_duration.py`
- 修改：`frontend/src/api/usageDurations.ts`
- 修改：`frontend/src/components/UsageDurationPanel.vue`
- 测试：`backend/tests/test_usage_duration_service.py`
- 测试：`backend/tests/test_usage_duration_summary.py`
- 测试：`backend/tests/test_usage_duration_admin_api.py`
- 测试：`backend/tests/test_usage_duration_api.py`
- 测试：`frontend/src/api/usageDurations.test.ts`
- 测试：`frontend/src/components/UsageDurationPanel.test.ts`

### 步骤

- [ ] **5.1 保留 latest-per-device 查询**

  保留 `(package_name, device_id)` 分区和 `server_ts DESC, id DESC` 排序；先取每设备最新报告，再按包名聚合。新增同设备多条报告、同时间戳 ID 破平局、机型变化和累计时长不重复相加测试。

- [ ] **5.2 汇总一包一行**

  移除 summary 的 `device_model` 分组，返回每包设备数、最新累计时长总和、平均值、四个桶数量/占比和最大最后上报时间。桶固定：`<=300`、`301–600`、`601–899`、`>=900`。空设备集的平均值/桶占比保持 `null`。

- [ ] **5.3 保留 nullable device_model 和排序兼容**

  summary 响应保留 `device_model: null` 字段供旧客户端解码；`sort_by=device_model` 仍接受，但显式降级为 `package_name`，不能恢复机型分组。设备明细 endpoint 的 `device_model` 改为可选：缺省返回包内所有最新设备，传值继续按机型筛选。

- [ ] **5.4 保持 usage 范围/协议规则**

  空 `package_name` 仍查询全部包；日期范围仍最多 31 个北京时间日；上报 schema 仍只接受 `duration_s` 的 `1–3600`，`0`、负数、超 3600 和非整数继续 422。

- [ ] **5.5 更新默认 UI**

  `UsageDurationPanel.vue` 行键改为 scope + package，默认只渲染包级行，不展示单设备/机型汇总；显式展开才调用设备明细。前端类型保留 nullable `device_model`，并测试多机型仍只有一行。

## 6. 更新旧时长定义文档

### 文件

- 修改：`docs/48-SDK-USAGE-DURATION-DESIGN-20260929.md`

### 步骤

- [ ] 写明 `duration_s` 是单条报告时设备累计在线时长。
- [ ] 写明选定范围内每个 `(package_name, device_id)` 按 `server_ts,id` 取最新报告后再按包聚合。
- [ ] 写明四桶：`<=300`、`301–600`、`601–899`、`>=900`。
- [ ] 写明包级 summary 一包一行、机型仅 nullable 兼容字段/可选明细维度。
- [ ] 添加同一设备多条历史报告但只计最新累计值的示例。

## 7. 数据库和真实 PostgreSQL 回归

### 文件

- 新增：`backend/tests/test_log_scope_and_usage_integration.py`
- 保持不变：正式表 ORM/SQL，不新增 `job_id` 或迁移脚本。

### 步骤

- [ ] 为真实 PostgreSQL 16 增加 `@pytest.mark.integration` 测试，使用环境变量 `SDK_LOG_SCOPE_TEST_DATABASE_URL`。
- [ ] 只接受 loopback 主机和专用数据库名 `sdk_scope_test_<suffix>`；测试建立隔离 schema/临时表或清理自有 fixture，不连接生产库。
- [ ] 插入 fixture 覆盖：重叠任务、同 exact scope 多任务、任务状态排序、成功/失败 H1、无 H1、成功 H1 真零、usage 多机型和同设备历史报告。
- [ ] 真实执行 summary SQL、formal metrics snapshot 上限 SQL、latest job SQL、usage latest-per-device/package SQL，并断言结果和边界。
- [ ] 若环境无 PG16 或 `SDK_LOG_SCOPE_TEST_DATABASE_URL` 未设置，命令可以 skip，但验收报告必须明确“真实 PostgreSQL 回归未验证”；不得写成“测试通过”。

## 8. 测试命令与验收证据

### 8.1 后端单元/API/SQL 编译回归

```powershell
cd backend
python -m pytest tests/test_log_analysis_scope.py tests/test_log_metrics_api_v2.py tests/test_log_metrics_service_v2.py tests/test_log_parse_job_service_v2.py tests/test_log_analysis_service.py tests/test_usage_duration_service.py tests/test_usage_duration_summary.py tests/test_usage_duration_admin_api.py tests/test_usage_duration_api.py -q
```

### 8.2 真实 PostgreSQL 回归

```powershell
cd backend
python -m pytest -m integration tests/test_log_scope_and_usage_integration.py -q
```

必须记录是通过、跳过（未验证）还是失败；无连接环境不能以静态 SQL 编译结果替代。

### 8.3 前端

```powershell
cd frontend
npm test -- --run src/utils/logAnalysisScope.test.ts src/components/LogAnalysisFilters.test.ts src/views/LogViewer.test.ts src/components/LogParseTaskPanel.test.ts src/components/LogMetricsPanel.test.ts src/components/PackageProfileCell.test.ts src/components/LogColumnSettings.test.ts src/components/UsageDurationPanel.test.ts src/api/logMetrics.test.ts src/api/logAnalysis.test.ts src/api/usageDurations.test.ts
npm run build
```

### 8.4 静态/保护范围

- [ ] `git diff --check`。
- [ ] `rg` 确认 `LogViewer.vue` 不再导入/调用旧 summary/details API。
- [ ] `rg` 确认 analysis mount/query/refresh/轮询路径没有 `postParseJob`，只有显式按钮路径允许调用。
- [ ] `rg` 确认没有新增正式表 `job_id`、迁移脚本或生产写操作。
- [ ] 确认 `docs50` 仍是未暂存脏文件且未被提交。

## 9. 提交、审查、发布和回滚

本次修订先提交文档，等待主审确认后才允许进入实现；当前提交不包含业务代码。

后续实现建议按小提交拆分：

1. `test: lock analysis scope and latest job contract`；
2. `feat: show formal metrics and task states in log viewer`；
3. `feat: aggregate usage duration by package`；
4. `docs: clarify cumulative usage duration semantics`；
5. `test: add PostgreSQL scope and usage regression`。

发布前必须有前后端同版本构建、单元/API 测试、真实 PostgreSQL 回归结果（或明确未验证）和保护范围检查。发布只做只读验证，不创建生产 parse job。

回滚只恢复上一应用版本，不做数据库逆迁移、不删除历史正式结果或 usage 报告。共享正式表的重叠发布不通过回滚补偿；若需重新发布期望范围，必须由管理员明确创建新任务。
