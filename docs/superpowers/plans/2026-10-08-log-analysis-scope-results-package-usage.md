# 日志分析生效范围、正式结果与包级在线时长实施计划

> **目标：** 将日志分析页面、显式解析任务、正式 H1/click 结果和在线时长汇总统一到同一组北京时间范围与包名条件下；主结果不再使用 `LogDecode` 聚合冒充正式解析结果；usage 默认按包名一行汇总。  
> **基线：** `d08718c7bc0877415eaf04d871a1b5878154a6c2`（当前分区维护提交）  
> **目标分支：** `codex/log-analysis-scope-package-usage-20261008`  
> **实施状态：** 仅为审查用计划；本轮不修改业务代码、不创建生产任务、不部署。  
> **技术栈：** Python 3.12、FastAPI、SQLAlchemy 2.x、PostgreSQL、Vue 3、TypeScript、Pytest、Vitest。

## 0. 执行约束与完成定义

### 0.1 保护范围

- 保留并忽略用户已有的 `docs/50-LOG-METRICS-DEVICE-DURATION-H1-EXPORT-IMPLEMENTATION-20260930.md` 工作区修改；不提交、不覆盖。
- 不修改分区维护提交及其代码、文档和部署文件。
- 不修改 SDK 上传协议、原始事件写入、配置系统和旧 8102 相关范围。
- 不运行生产解析任务，不做生产回填，不执行部署。

### 0.2 实施完成定义

只有同时满足以下条件才可进入发布审查：

1. 查询、刷新、解析任务创建、任务成功后的刷新和 usage 查询均由同一个规范化范围驱动。
2. 主结果只使用显式任务成功发布的正式 H1/click 表；旧 `LogDecode` 仅作兼容区或兼容 API。
3. 无任务、运行中、失败、成功空结果、成功有结果均有稳定 UI 状态和测试。
4. usage summary 对每个包名仅有一行，输入为范围内每台设备的最新累计报告。
5. `docs/48-SDK-USAGE-DURATION-DESIGN-20260929.md` 已更新为当前口径。
6. 后端和前端相关测试、构建、类型检查和 `git diff --check` 通过。
7. 无数据库迁移，无保护范围改动，无生产写操作。

## 1. 建立规范化范围契约

### 文件

- 修改：`frontend/src/components/LogAnalysisFilters.vue`
- 修改：`frontend/src/api/logMetrics.ts`
- 修改：`frontend/src/views/LogViewer.vue`
- 修改：`backend/app/schemas/log_metrics_schemas.py`
- 修改：`backend/app/schemas/log_analysis_schemas.py`
- 修改：`backend/app/api/admin/log_analysis.py`
- 修改：`backend/app/api/admin/log_metrics.py`
- 修改：`backend/app/services/log_parse_job_service.py`
- 测试：`frontend/src/components/LogAnalysisFilters.test.ts`
- 测试：`frontend/src/api/logMetrics.test.ts`
- 测试：`frontend/src/views/LogViewer.test.ts`
- 测试：`backend/tests/test_log_analysis_api.py`
- 测试：`backend/tests/test_log_metrics_api_v2.py`
- 测试：`backend/tests/test_log_parse_job_service_v2.py`

### 步骤

- [ ] **1.1 记录基线并建立失败测试**

  在改代码前保存 `BASE_SHA`、当前分支和工作区状态；确认 `docs50` 是唯一既有脏文件。新增或补充测试，先断言以下当前缺陷：

  - 刷新事件带有新日期/小时/包名快照时，页面请求必须使用该快照；
  - summary 请求必须传递 `hour_from` 和 `hour_to`；
  - 解析任务 POST 只能由显式解析动作触发；
  - `business_hour_utc_range` 的小时边界和 7 天限制保持一致。

  运行：

  ```powershell
  cd backend
  python -m pytest tests/test_log_analysis_api.py tests/test_log_metrics_api_v2.py tests/test_log_parse_job_service_v2.py -q
  cd ..\frontend
  npm test -- --run src/components/LogAnalysisFilters.test.ts src/api/logMetrics.test.ts src/views/LogViewer.test.ts
  ```

- [ ] **1.2 统一前端生效范围状态**

  `LogViewer.vue` 维护一个明确的 `appliedScope`，而不是让 summary、metrics、parse job 各自从不同状态拼参数。`query(value)`、`refresh(value)`、`reset(value)` 均先校验/规范化并保存完整快照，再把同一对象传给所有请求。

  允许抽取纯函数到 `frontend/src/utils/logAnalysisScope.ts`，职责限定为：规范化默认值、校验包名/日期/小时/7 天限制、生成 API 参数和比较范围；不得在该工具中发请求或创建任务。若抽取该文件，新增 `frontend/src/utils/logAnalysisScope.test.ts`。

- [ ] **1.3 保持最近 3 天初始默认和 7 天上限**

  初始值继续由北京时间当天计算最近 3 个自然日；不是浏览器本地日期，也不是滚动 72 小时。用户提交时保留现有最多 7 个日历日约束，前后端都校验；开始/结束小时仍按照现有 `hour_from`/`hour_to` 合同解释，结束小时包含在范围内。

- [ ] **1.4 使后端所有相关请求使用同一范围**

  对正式指标、任务创建、任务详情/覆盖率和旧 summary 兼容查询统一接受包名、日期和小时。所有数据库过滤继续通过 `business_hour_utc_range` 生成 UTC 半开区间，不在 API 层手写时区偏移。

  旧仅日期的 API 字段不能悄悄忽略小时：兼容调用若未提供小时可继续使用整日；一旦提供小时，必须将小时带入查询。

### 验证点

- [ ] 组件测试证明修改表单后点击刷新，请求参数等于当前表单完整快照。
- [ ] API 测试证明小时被传入 service 并影响查询边界。
- [ ] 静态检查确认页面挂载、刷新、查询、轮询和指标面板初始化都没有 POST parse job。

## 2. 将正式 H1/click 结果设为主分析路径

### 文件

- 修改：`frontend/src/views/LogViewer.vue`
- 修改：`frontend/src/components/LogMetricsPanel.vue`
- 修改：`frontend/src/components/LogParseTaskPanel.vue`
- 修改：`frontend/src/api/logMetrics.ts`
- 修改：`backend/app/services/log_metrics_service.py`
- 修改：`backend/app/services/log_parse_job_service.py`
- 修改：`backend/app/api/admin/log_metrics.py`
- 保留兼容：`backend/app/services/log_analysis_service.py`
- 保留兼容：`backend/app/api/admin/log_analysis.py`
- 测试：`frontend/src/components/LogMetricsPanel.test.ts`
- 测试：`frontend/src/components/LogParseTaskPanel.test.ts`（若文件已存在则扩展；不存在时创建）
- 测试：`frontend/src/views/LogViewer.test.ts`
- 测试：`backend/tests/test_log_metrics_service_v2.py`
- 测试：`backend/tests/test_log_metrics_api_v2.py`
- 测试：`backend/tests/test_log_parse_job_service_v2.py`

### 步骤

- [ ] **2.1 先固定主结果来源的契约测试**

  测试主分析页面在有成功任务时只请求/展示 `H1Declaration`、`LogClickAttempt` 及任务状态；不能以 `get_log_analysis_summary` 的 `LogDecode` 字段作为正式 H1/click 数值。

  保留旧 summary API 的兼容测试，但将其响应标记为 legacy/compatibility 语义，不把它作为主结果断言来源。

- [ ] **2.2 补齐任务状态和结果状态模型**

  将任务状态、任务范围、`snapshot_end`、扫描数量和正式发布摘要作为 `LogMetricsPanel` 可用的状态输入。状态映射固定为：

  ```text
  scope_required -> no_job -> pending/running -> failed/cancelled
                                      \-> success_empty
                                      \-> success_non_empty
  ```

  `success_empty` 必须来自成功任务且正式结果行数为 0；不能将 HTTP 空数组、网络错误、尚未有任务和真实零结果混为一类。

- [ ] **2.3 将 `LogMetricsPanel` 设为正式结果主面板**

  继续使用现有正式指标接口和已有配置/目标/失败原因/H1 下钻能力，增加：

  - 当前生效范围摘要；
  - 最近任务状态和快照结束时间；
  - 扫描事件/H1/click/无 H1/失败 H1 计数；
  - 无任务、运行中、失败、成功空结果和成功有结果的独立文案。

  不修改正式表语义，不把任务暂存表直接暴露给页面。

- [ ] **2.4 处理旧 `LogDecode` 汇总**

  `LogViewer.vue` 不再把旧 summary 表作为主结果区。若包资料编辑、列配置或兼容排查功能仍依赖旧表：

  - 保留兼容请求和组件，但移到折叠/次级的“原始事件兼容汇总”；
  - 所有标题明确写明 `SdkEvent + LogDecode`，禁止使用“正式 H1 指标”等字样；
  - 只保留必要的包资料和指标配置能力，不复制正式结果数值；
  - 旧 detail 下钻不得影响正式指标刷新。

  如果现有组件已能保留配置而不显示旧指标，则优先减少主页面并避免重复请求；不删除后端兼容 API。

- [ ] **2.5 固定显式解析和成功刷新行为**

  `LogParseTaskPanel` 只在用户点击解析时调用 POST；其 scope 取自 `appliedScope`。任务成功后发出带任务 scope 的刷新事件，`LogViewer` 使用该 scope 重新加载正式结果和任务摘要，不回读可能已变化的草稿。

  任务轮询只读 GET；切换范围时清理旧任务展示，但不得取消或创建新任务，除非已有明确取消按钮语义。

- [ ] **2.6 明确快照语义的 UI 文案**

  在任务详情或正式结果摘要中显示：任务请求范围、`snapshot_end`、“该时间点之后到达的日志需新建任务纳入”。不要把任务完成时间替代 `snapshot_end`，也不要暗示一次任务会持续追踪范围内后续日志。

### 验证点

- [ ] 成功任务有正式数据时，页面数值与正式表聚合结果一致。
- [ ] 成功任务但正式 H1/click 为 0 时，显示“已完成、正式结果为 0”而不是加载态或错误。
- [ ] 当前范围无任务时，显示“尚未执行显式解析”，即使旧 raw/legacy summary 有原始事件也不改变此状态。
- [ ] 任务失败/取消时显示可重试状态，不读取未发布暂存结果。
- [ ] 解析成功后刷新同一 scope；用户在任务运行期间修改草稿不会改变运行中任务的 scope。

## 3. 收敛在线时长为包级一行

### 文件

- 修改：`backend/app/services/usage_duration_service.py`
- 修改：`backend/app/api/admin/usage_duration.py`
- 修改：`backend/app/schemas/usage_duration_schemas.py`（若当前契约在其他 schema 文件，按实际定义调整）
- 修改：`frontend/src/api/usageDurations.ts`
- 修改：`frontend/src/components/UsageDurationPanel.vue`
- 修改：`frontend/src/components/UsageDurationPanel.test.ts`
- 测试：`frontend/src/api/usageDurations.test.ts`
- 测试：`backend/tests/test_usage_duration_service.py`
- 测试：`backend/tests/test_usage_duration_summary.py`
- 测试：`backend/tests/test_usage_duration_admin_api.py`
- 兼容测试：`backend/tests/test_usage_duration_api.py`

### 步骤

- [ ] **3.1 先锁定累计/最新报告口径**

  为同一设备多条报告补充回归测试：按 `server_ts DESC, id DESC` 只选最新一条；其 `duration_s` 已是累计值，只计一次。测试设备机型变化、同一时间戳用 ID 破平局、空范围和 `duration_s=0`。

- [ ] **3.2 改 summary 聚合粒度**

  保留 `build_latest_usage_query` 的每包每设备最新记录选择逻辑，移除 summary 的 `device_model` 分组。按 `package_name` 计算：设备数、最新累计时长总和、平均值、四个桶的数量和占比、最大最后上报时间。

  四个桶继续复用现有常量、边界和命名；本次不改变桶定义。没有设备时，平均值和各桶占比使用现有 API 约定的 `null`，不要伪造 `0`。

- [ ] **3.3 收敛 summary API 契约**

  summary 响应类型移除主页面必需的 `device_model` 分组语义，排序白名单改为包级字段。若为兼容旧客户端暂时接受 `device_model` sort 参数，必须明确忽略/降级规则并增加测试，不得让后端重新按机型返回多行。

- [ ] **3.4 保留设备明细接口兼容能力**

  `get_usage_devices` 继续接受旧的 `device_model` 过滤；同时允许缺省机型时按包名返回全部最新设备，供显式下钻使用。该接口不是默认 summary 页面数据源，不改变默认渲染。

- [ ] **3.5 更新前端展示**

  `UsageDurationPanel.vue`：

  - 行键从“范围 + 包名 + 机型”改为“范围 + 包名”；
  - 默认列只渲染包级汇总；
  - 不渲染机型汇总行或设备明细；
  - 显式下钻时才请求 devices，并可继续展示机型/设备字段；
  - 处理包名切换、空结果、桶占比 `null` 和最后上报时间。

### 验证点

- [ ] 一个包包含多个机型时 summary 只有一行。
- [ ] 两台设备各有多条历史报告时，总时长等于两台设备各自最新累计值之和。
- [ ] 设备详情不影响默认 summary 行数；旧机型过滤调用仍通过兼容测试。
- [ ] UI 不会因为机型变化产生重复 key 或重复包行。

## 4. 更新旧时长定义文档

### 文件

- 修改：`docs/48-SDK-USAGE-DURATION-DESIGN-20260929.md`

### 步骤

- [ ] 将 `duration_s` 明确写为“单条报告时设备累计在线时长”。
- [ ] 将汇总算法明确写为“所选北京时间范围内，每个包名/设备取最新报告，再按包名聚合”。
- [ ] 删除或改写任何会让读者把所有历史报告直接求和的旧表述。
- [ ] 明确包级 summary 一包一行；机型和设备仅作为可选下钻，不是默认汇总维度。
- [ ] 增加一个含同设备多次报告的数值示例，证明历史报告不重复相加。

## 5. 数据库与迁移判断

- [ ] 检查现有 `sdk_log_h1_declarations`、`sdk_log_click_attempts`、`sdk_log_reparse_jobs` 和 `sdk_usage_durations` 字段、索引足以支持本计划。
- [ ] 若检查通过，不创建 SQL、ORM 表结构或数据迁移；在 PR/发布说明中明确“无数据库迁移”。
- [ ] 不删除旧 summary 相关表/字段、`LogDecode`、历史正式结果、usage 历史报告或旧 API。
- [ ] 若实施中确实发现字段不足，必须停止并重新提交迁移设计；不得在本计划范围内临时修改生产 schema。

## 6. 测试矩阵与命令

### 6.1 后端

- [ ] 范围和小时边界：`backend/tests/test_log_analysis_api.py`、`backend/tests/test_log_metrics_api_v2.py`。
- [ ] 任务快照、`snapshot_end`、无暂存泄漏、显式创建：`backend/tests/test_log_parse_job_service_v2.py`。
- [ ] 正式 H1/click 聚合和空结果语义：`backend/tests/test_log_metrics_service_v2.py`。
- [ ] usage 每设备最新值、包级聚合、四桶占比：`backend/tests/test_usage_duration_service.py`、`backend/tests/test_usage_duration_summary.py`。
- [ ] API 兼容参数和排序：`backend/tests/test_usage_duration_admin_api.py`、`backend/tests/test_usage_duration_api.py`。

建议命令：

```powershell
cd backend
python -m pytest tests/test_log_analysis_api.py tests/test_log_metrics_api_v2.py tests/test_log_parse_job_service_v2.py tests/test_log_metrics_service_v2.py tests/test_usage_duration_service.py tests/test_usage_duration_summary.py tests/test_usage_duration_admin_api.py tests/test_usage_duration_api.py -q
```

### 6.2 前端

- [ ] `LogAnalysisFilters.test.ts`：最近 3 天、7 天上限、完整快照、小时校验。
- [ ] `LogViewer.test.ts`：query/refresh 使用新范围、无自动 POST、成功任务同范围刷新、legacy 不作为主结果。
- [ ] `LogMetricsPanel.test.ts` 和 `LogParseTaskPanel.test.ts`：正式结果和任务状态矩阵。
- [ ] `UsageDurationPanel.test.ts`：一包一行、同设备取最新、显式设备下钻。
- [ ] `logMetrics.test.ts`、`usageDurations.test.ts`：请求参数和响应类型。

建议命令：

```powershell
cd frontend
npm test -- --run src/components/LogAnalysisFilters.test.ts src/views/LogViewer.test.ts src/components/LogMetricsPanel.test.ts src/components/LogParseTaskPanel.test.ts src/components/UsageDurationPanel.test.ts src/api/logMetrics.test.ts src/api/usageDurations.test.ts
npm run build
```

### 6.3 静态和保护范围检查

- [ ] `git diff --check`。
- [ ] 前端类型检查/构建通过。
- [ ] 搜索主页面不再把 `LogDecode` summary 响应当作正式 H1/click 指标。
- [ ] 搜索页面挂载、查询、刷新、轮询路径没有 `postParseJob` 调用。
- [ ] 确认只修改本计划列出的实现、测试和 `docs/48`；`docs/50` 的既有修改保持原样且不进入提交。

## 7. 提交顺序与审查检查点

本轮只提交规格和计划文档；后续实施建议按以下小提交进行，避免把兼容清理和业务口径混在一起：

1. `test: lock unified log analysis scope behavior`：范围/刷新/小时/无自动解析测试。
2. `feat: use formal parse results as analysis primary path`：正式结果状态、任务快照展示和 legacy 次级区。
3. `feat: aggregate usage duration by package`：后端一包一行、设备明细兼容和前端展示。
4. `docs: clarify cumulative usage duration semantics`：更新 `docs/48`。
5. `test: verify log analysis and package usage release`：补齐端到端/构建/保护范围验证。

每个提交前都确认 `docs/50` 未被 stage。实施前审查点：

- [ ] 用户确认本规格和计划。
- [ ] 用户确认 `BASE_SHA=d08718c7bc0877415eaf04d871a1b5878154a6c2` 作为实现起点。
- [ ] 用户确认旧 summary 是“兼容次级区”还是完全移除其前端显示；默认按本计划的兼容次级区实施，以保留包资料/指标配置。

## 8. 发布、观测与回滚

### 发布前

- [ ] 只在测试数据或只读环境验证；不创建生产 parse job。
- [ ] 检查前后端版本一起发布，避免新页面调用旧 API 契约。
- [ ] 记录构建产物校验值和发布前应用版本，保留回滚目标。

### 发布后只读验证

- [ ] 选择一个有正式任务、一个无任务、一个成功空结果范围，确认 UI 三态/多态文案。
- [ ] 修改范围后点击刷新，确认请求参数与生效范围一致。
- [ ] 检查一包多机型只出现一行，抽查总时长和数据库最新设备值一致。
- [ ] 确认无后台自动解析任务新增。

### 回滚

回滚只恢复上一应用版本，不执行数据库逆迁移、不删除正式结果、不删除 usage 历史报告。由于本计划不要求 schema 变更、不自动创建生产任务，回滚不会改变数据事实；旧 summary 和设备明细兼容 API 可继续服务旧页面。
