# 日志分析生效范围、正式结果与包级在线时长设计

> 日期：2026-10-08
> 基线：`d08718c7bc0877415eaf04d871a1b5878154a6c2`
> 分支：`codex/log-analysis-scope-package-usage-20261008`
> 状态：根据独立审查意见修订，待主审确认；当前不实施、不部署
> 业务时区：`Asia/Shanghai`（UTC+8）

## 1. 背景与目标

当前日志分析页把两种事实混在一起：旧 summary 使用 `SdkEvent + LogDecode` 聚合，正式指标使用显式解析任务发布的 H1/click 表。原始事件有数据而正式解析没有数据时，旧表会造成“解析成功但指标为 0”的误判。刷新还可能丢弃表单最新的日期、小时或包名。

在线时长已经能够在范围内选择每台设备最新报告，但 summary 仍按包名和机型分组；同时，`duration_s` 的累计语义在旧文档中没有被严格固定。

本设计只解决以下范围：

1. analysis 查询、刷新和显式解析统一使用当前合法 draft 的完整范围；
2. analysis 主 UI 只展示正式 H1/click 结果和解析任务状态，移除旧 `LogDecode` summary 表；
3. 增加按精确范围查询最近解析任务状态的契约，并正确处理共享正式表、重叠重解析和快照上限；
4. usage 保持自身独立的 31 天规则和空包名查全部，改为每包一行、每设备取范围内最新累计报告；
5. 更新旧时长定义文档和可执行验收边界。

## 2. 范围模型

### 2.1 AnalysisScope

analysis 的规范化范围包含：

```text
package_name: 必填、完全匹配、规范化后的包名
date_from/hour_from: 北京时间开始日期和小时
date_to/hour_to: 北京时间结束日期和小时，结束小时包含在范围内
```

后端统一通过 `business_hour_utc_range` 得到 UTC 半开区间：

```text
exact scope = (package_name, range_start_utc, range_end_utc)
查询条件 = server_ts >= range_start_utc AND server_ts < range_end_utc
```

例如北京时间 `09:00` 到 `11:00` 的结束边界是 `12:00`。analysis 日期差最多 6 天，即最多 7 个北京时间自然日；开始/结束小时必须构成正向连续区间。formal metrics 查询和创建解析任务必须调用同一个后端范围校验器，不能各自实现日期上限或时区转换。

页面初始 draft 按北京时间当天计算最近 3 个自然日，不是最近 72 小时。只有用户提交合法 draft 后才成为 `appliedAnalysisScope`。

### 2.2 UsageScope

usage 与 analysis 使用独立范围状态和校验，不共享“包名必填”规则：

- `package_name` 可为空；为空表示查询全部包；
- 日期/小时继续使用现有 usage 规则，最多 31 个北京时间日；
- `duration_s` 上报协议继续只接受 `1–3600`，`0` 仍拒绝；
- usage 初始默认值可以继续复用当前页面约定，但不能被 analysis 的 7 天上限或包名必填规则覆盖。

## 3. Analysis 查询、刷新与显式解析

### 3.1 当前合法 draft 的应用规则

`LogAnalysisFilters.vue` 发出的 query/refresh/reset 事件都带完整 draft 快照。解析按钮事件链固定为：

```text
LogAnalysisFilters
  -- query/refresh/update:modelValue --> LogViewer 保存 draft snapshot
LogParseTaskPanel
  -- request-parse(snapshot) --> LogViewer
LogViewer
  -- 校验当前最新 draft --> appliedAnalysisScope
  -- 合法后 POST /parse-jobs --> TaskPanel 轮询任务
```

组件契约固定为：

- `LogAnalysisFilters` 维护 draft，`update:modelValue`、`query`、`refresh`、`reset` 均传完整 `LogAnalysisFilterValues`；
- `LogParseTaskPanel` 接收当前 draft/applied scope 作为 props，只 emit `request-parse`，不直接读取表单、不自行校验旧值、不直接 POST；
- `LogViewer` 接收 `request-parse` 后从当前最新 draft 取值，执行同一合法性校验，合法时保存 `appliedAnalysisScope` 并 POST；非法时显示校验错误且不得 POST。

因此用户修改表单后不点击查询、直接点击解析时，解析使用最新 draft；用户提交非法 draft 时，解析按钮事件仍不能绕过校验。

`LogViewer.vue` 必须在处理 query/refresh/reset/request-parse 时：

1. 校验并保存该快照为 `appliedAnalysisScope`；
2. 用同一个快照触发任务状态查询、formal metrics 查询和页面展示；
3. 不从旧的 `appliedFilters`、旧 `metricScope` 或闭包重新拼参数；
4. 用户只修改 draft 而未提交时，不改变当前结果；
5. 查询、刷新、页面挂载、轮询和指标面板初始化均不得创建解析任务。

只有用户明确点击 `LogParseTaskPanel.vue` 的解析按钮才允许 POST 创建任务。任务成功后使用该任务创建时保存的 scope 刷新；如果当前 `appliedAnalysisScope` 已经不同，则丢弃旧任务完成事件，不得覆盖新范围结果。

### 3.2 共享后端范围校验

新增一个 analysis 范围解析/校验 helper，至少由以下路径共同调用：

- `POST /log-analysis/parse-jobs` 的请求模型和 service；
- `/log-analysis/metrics/*` 的 scope dependency/service；
- 最近任务状态查询的 exact scope service。

helper 负责包名规范化、北京时间小时转 UTC、正向区间和 7 个自然日上限。usage 不调用该 helper，继续由 `usage_duration_service.resolve_usage_summary_range` 管理 31 天和空包名。

## 4. 最近解析任务状态契约

### 4.1 精确查询键

新增最近任务状态查询，服务层的唯一查询键是：

```text
(package_name, range_start_utc, range_end_utc)
```

其中 `range_start_utc` 和 `range_end_utc` 是完整、带时区的 UTC 半开边界，不允许只按日期、只按包名或只按任务创建日模糊匹配。HTTP 层可以继续接收页面的北京时间日期/小时并先经过共享 helper 转换；转换后的 exact tuple 必须原样传给 service 查询。

最近任务排序固定为：

```sql
ORDER BY created_at DESC, id DESC
LIMIT 1
```

没有匹配任务返回明确的 `data: null`，不能伪造空任务对象。静态路由必须注册在 `GET /log-analysis/parse-jobs/{job_id}` 之前；API 回归必须实际请求 `/latest`，确认不会被 `{job_id}` 路由解析为整数而返回 422。

### 4.2 `ParseJob` 类型与时间字段

前端 `ParseJob` 不得继承 `LogMetricScope`，因为任务响应当前没有、也不应假装包含 `date_from/hour_from/date_to/hour_to`。类型分别表达：

- 请求使用页面的 `LogMetricScope`；
- 任务响应使用任务 ID、状态、计数、进度和 UTC 范围边界。

响应增加或明确以下字段，字段定义必须以 UTC ISO 8601 为准：

```text
scope.package_name
scope.range_start_utc
scope.range_end_utc
snapshot_end_utc
```

现有旧时间字段如继续返回，必须在 API 文档中标注其时区和兼容语义；前端展示不得猜测，统一用 UTC 边界转换为北京时间显示。新进度 UI 使用 `total_count`、`processed_count`、`h1_count`、`failed_h1_count`、`no_h1_count`；`decoded_count` 和 `failed_count` 旧字段不作为本次新进度展示依据。

### 4.3 任务状态和 formal 结果状态

最近任务是当前 scope 的状态来源。成功状态按以下互斥顺序判定：

| 最新任务状态 | 主 UI 行为 |
|---|---|
| 无任务 | 提示尚未对该 exact scope 执行显式解析，不展示 formal metrics |
| `pending/running` | 展示任务范围、UTC/北京时间快照、进度和等待状态，不把旧正式行显示为此次成功 |
| `failed/cancelled` | 展示失败/取消原因和失败计数，不把旧正式结果标记为此次成功 |
| `success` 且 `total_count = 0` | `no_source`，明确提示范围内没有源事件 |
| `success` 且有成功 H1 | 继续区分 `true_zero` 与 `success_nonzero`，并显示任务 snapshot 信息 |
| `success` 且成功 H1 为 0、失败 H1 大于 0 | `all_failed_h1`，同时展示 `no_h1_count` |
| `success` 且成功 H1 为 0、失败 H1 为 0、有原始事件 | `no_h1` |

成功任务的细分必须可测试：

- `no_source`：任务成功且 `total_count = 0`；
- `all_failed_h1`：成功 H1 为 0 且 `failed_h1_count > 0`，同时显示 `no_h1_count`；
- `no_h1`：成功 H1 为 0、`failed_h1_count = 0` 且存在原始事件；
- `true_zero`：成功 H1 大于 0，但计划/实际/成功等正式指标确实为 0；
- `success_nonzero`：成功 H1 大于 0 且至少一个正式指标非零。

`all_failed_h1`、`no_h1` 和 `true_zero` 互斥，不能用“成功 H1 为 0”同时包含 `true_zero`。

### 4.4 解析计数不变量

按现有 worker 的计数语义，`h1_count` 是成功 H1 与失败 H1 的总数，`failed_h1_count` 是其中失败 H1 的子集；因此只有在测试确认不变量成立时，才允许使用：

```text
successful_h1_count = h1_count - failed_h1_count
```

如果现有 worker 或历史任务不能保证该不变量，正式 scope/snapshot 查询必须直接从正式 H1 表按 `status` 计算成功 H1 数，不能由任务计数推断。`decoded_count` 和 `failed_count` 是旧进度字段；本次不修改 worker 语义，新进度 UI 不使用它们，避免把未更新字段显示成可信进度。

### 4.5 共享正式表和重叠重解析

本次不增加正式表 `job_id`，不做结果版本化，不创建迁移，也不承诺不可变的“某任务专属结果”。正式 H1/click 表是共享的已发布解析数据：

- 成功发布任务可以按其 scope 替换正式结果；
- 重叠任务可能更新相同正式表范围，最终正式数据由实际发布顺序决定；
- 任务状态和 snapshot 信息独立于正式表，不把正式行标记为属于某个 job；
- UI 只能表述“当前 exact scope 在选定 snapshot 上限内读取到的正式结果”，不能表述“job N 的不可变输出”。

formal metrics 查询必须带当前 exact scope，并在有最新成功任务时带 `snapshot_end_utc` 上限。后端校验 `range_start_utc < snapshot_end_utc <= range_end_utc`；`snapshot_end_utc <= range_start_utc` 继续返回 422，不扩大“空快照”语义。`no_source` 只表示合法非空 snapshot 区间内没有源事件。实际读取边界为：

```text
[range_start_utc, min(range_end_utc, snapshot_end_utc))
```

如果最新任务为 pending/running/failed/cancelled，页面不以该任务为成功依据，也不使用旧成功任务冒充当前任务成功。旧任务完成回调还必须通过 exact scope 比较和请求序列号检查，不能覆盖新的 `appliedAnalysisScope`。

## 5. 正式结果主 UI

### 5.1 移除旧主路径

`frontend/src/views/LogViewer.vue` 的旧“聚合结果”表、旧 `LogAnalysisDetail` 下钻及其 `LogDecode` summary 主路径全部从 analysis 主 UI 移除。不新增兼容面板，不在主页面保留旧 `LogDecode` 表的折叠版本。旧 summary/details 后端 API 和契约本身不修改，供既有外部调用方继续使用，但本页面不再调用它们。

### 5.2 正式结果界面和必要功能保留

正式结果界面由 `LogMetricsPanel.vue` 承载，继续读取：

- `sdk_log_h1_declarations` 的 overview/config/H1 数据；
- `sdk_log_click_attempts` 的 target/failure 数据；
- 最近任务状态和计数。

用户已配置的包资料和可配指标必须沿正式结果界面保留，具体位置和生命周期固定为：

1. `LogViewer.vue` 在当前 `appliedAnalysisScope.package_name` 变化后加载 `/package-profiles`；请求带序列号，旧包响应不得覆盖新包；
2. `LogMetricsPanel.vue` 的正式结果标题区域渲染三个 `PackageProfileCell`（alias/company/account），保存仍调用现有 `/package-profiles/{package_name}`，成功只更新当前正式面板本地资料，不触发解析；
3. `LogViewer.vue` 继续加载和保存 `/log-analysis/columns`，`LogColumnSettings.vue` 由正式结果标题区域的“配置指标”入口打开，`LogMetricsPanel.vue` 按当前保存的正式指标配置控制卡片/表格的显示；保存请求成功后才更新可见配置；
4. 配置和包资料的失败、取消、切换范围行为均由 `LogViewer.test.ts`、`LogMetricsPanel.test.ts`、`PackageProfileCell.test.ts` 和 `LogColumnSettings.test.ts` 覆盖；
5. 这些保留功能不再依赖旧 summary/details API 的响应行，也不改变旧 summary/details API。

columns preference 的旧 ID 不得由实施者自行猜测映射，固定如下：

| 旧 ID | formal ID/显示位置 | 处理 |
|---|---|---|
| `date` | `scope_label` | 显示当前 exact scope，作为 formal 必需项 |
| `package_name` | `package_name` | 原样保留，作为 formal 必需项 |
| `alias` | `profile.alias` | `PackageProfileCell` |
| `company` | `profile.company` | `PackageProfileCell` |
| `account` | `profile.account` | `PackageProfileCell` |
| `url` | `config_id` | 显示配置 ID；不伪造真实 URL |
| `expected_click_count` | `planned_click_count` | H1 `declared_click_count` 计划总数 |
| `actual_click_count` | `actual_click_count` | click `did_click=true` |
| `ad_click_count` | `ad_area_actual_count` | `banner + anchored` 的实际点击 |
| `interstitial_presentation_count` | `interstitial_presentation_count` | 正式 H1 插屏展示数 |
| `interstitial_click_count` | `interstitial_click_count` | 正式 H1 插屏点击数 |
| `parse_failure_count` | `failed_h1_count` | 任务/正式 H1 失败数 |
| `user_count` | 无一一对应项 | 保留为未映射历史设置，不渲染为正式指标 |
| `flow_count` | 无一一对应项 | 保留为未映射历史设置，不渲染为正式指标 |
| `average_duration_ms` | 无一一对应项 | H1 流程时长不等于本 formal 指标，保留设置不渲染 |
| `success_rate` | 无一一对应项 | `LogDecode.is_success` 不等于 click 响应成功率，保留设置不渲染 |

旧设置读取时必须保留未映射 ID（例如放入现有 preference JSON 的 `unmapped_legacy_columns` 或等价兼容字段），不能静默清空；正式设置界面把它们标为“历史列，无正式结果对应项”。用户显式保存后仍保留这些历史 ID 的记录，同时只用映射成功的 formal ID 控制渲染。新增/更新的 columns API 字段属于配置契约，不修改旧 summary/details API。

## 6. Formal H1/click 计数口径

正式指标服务必须过滤失败 H1：

- `status = failed` 的 H1 不进入成功声明、计划点击、配置分布、计划不一致或成功率等成功指标；
- 失败 H1 计入任务失败计数，并在 H1 明细/失败区显示 `parse_error` 或脱敏失败原因；
- 部分失败时，成功 H1 继续进入成功指标，失败 H1 只进入失败计数/明细，不能用总 `h1_count` 直接当成功声明数；
- 成功 H1 的 click failure 仍按 `navigation_code IS DISTINCT FROM 1` 进入失败明细和失败率；
- 无 H1、全部 H1 失败和成功 H1 但指标为 0 必须分别返回/展示，不能都由空数组或 0 值表达。

## 7. 在线时长包级汇总

### 7.1 计算

保留 `build_latest_usage_query` 的分区键和排序：

```text
PARTITION BY (package_name, device_id)
ORDER BY server_ts DESC, id DESC
```

在范围内每个设备只保留最新报告，再按 `package_name` 一行聚合。summary 字段包括：设备数、最新累计时长总和、平均值、桶数量/占比和最大最后上报时间。

四个桶固定为：

```text
le_300: duration_s <= 300
301_600: 301 <= duration_s <= 600
601_899: 601 <= duration_s <= 899
ge_900: duration_s >= 900
```

`duration_s` 是该设备在报告时的累计时长，同一设备历史报告不能重复相加。空设备集的平均值和桶占比继续使用 `null` 协议。

### 7.2 API 兼容和 UI

- usage summary 每个包名一行；`device_model` 字段保留为 nullable 兼容字段，包级行返回 `null`，不再按它分组；
- 旧 `sort_by=device_model` 参数继续接受，但明确降级为 `package_name` 排序，不改变返回粒度；
- 设备明细接口的 `device_model` 改为 nullable/可选：缺省返回包内全部最新设备，传值继续按机型过滤；
- 默认 UI 只渲染包级行，行键为范围 + 包名；只有用户明确下钻时才请求设备明细；
- usage 仍允许空包名查询全部包，仍拒绝超过 31 天的范围；上报协议仍拒绝 `0` 和超出 `1–3600` 的值。

## 8. 迁移判断

不新增正式表 `job_id`，不增加结果版本表，不做数据回填，不删除旧表/旧字段/历史结果，不需要数据库 schema 迁移。需要修改的是 API/service 查询、前端类型/展示、现有列配置显示语义和文档。

旧 `LogDecode` summary/details API 不修改；移除的是 `LogViewer.vue` 对它们的主 UI 依赖。包资料、列配置 API 和数据继续保留。

## 9. 验收标准

1. analysis 初始 draft 是最近 3 个北京时间自然日；提交超过 7 个北京时间日或非法小时被前后端共同拒绝。
2. analysis query/refresh/parse 使用当前合法 draft；刷新实际请求不丢包名、日期或小时；usage 空包名仍查全部且 31 天规则不变。
3. 页面挂载、query、refresh、轮询和指标面板初始化不创建 parse job；只有显式解析按钮 POST。
4. 未提交 draft 点击解析使用最新 snapshot；非法 draft 不 POST；TaskPanel 只 emit `request-parse`。
5. 最近任务按 `(package_name, range_start_utc, range_end_utc)` 精确匹配，按 `created_at DESC, id DESC` 选最新；`/latest` 静态路由在 `/{job_id}` 前且请求不会 422；无任务返回 `null`。
6. `ParseJob` 不伪造 date/hour 字段；UTC 范围和 snapshot 上限可可靠转换为北京时间展示。
7. analysis 主 UI 不再渲染旧 `LogDecode` summary/details；正式指标、包资料和可配指标仍在 `LogMetricsPanel` 正式界面可用。
8. pending/running 显示新进度字段；不展示未更新的 `decoded_count/failed_count`；failed/cancelled 不把旧结果标成当前任务成功；旧任务完成不会覆盖新 applied scope。
9. all-failed、部分失败、no-H1、true-zero、no-source 分别可识别；失败 H1 不进入成功指标计数但可查看失败明细。
10. `h1_count`/`failed_h1_count` 不变量经过 worker 测试确认后才推导成功 H1，否则按正式表 status 查询。
11. formal metrics 只读 exact scope 与合法 snapshot 上限；重叠任务行为按共享正式表语义展示，不宣称任务级不可变结果。
12. usage 多机型一包仅一行；每设备只计范围内最新累计报告；四个桶边界和 `device_model=null` 兼容字段符合本设计。
13. 旧 columns ID 按固定表映射；无法对应项保留且不渲染，不静默清空用户设置。
14. `docs/48-SDK-USAGE-DURATION-DESIGN-20260929.md` 写明累计时长和最新设备报告口径。
15. 真实 PostgreSQL 回归必须执行；若环境没有隔离 PG16，验收报告明确标记“未验证”，不能以编译通过替代。

## 10. 发布与回滚

本变更不执行数据库迁移、不创建生产任务、不回填生产数据。前后端作为同一应用版本发布，发布后只做只读范围验证和页面状态验证。

回滚只恢复上一应用版本，不执行数据库逆迁移，不删除历史正式结果或在线时长报告。共享正式表的重叠发布行为不通过回滚补偿；若需重新得到期望正式结果，必须由管理员在明确范围下重新创建解析任务。

## 11. 保护范围

- 分区维护及其安装/回滚文档；
- SDK 上传协议、原始事件写入链路；
- 配置系统；
- 旧 8102；
- 用户已有的 `docs/50-LOG-METRICS-DEVICE-DURATION-H1-EXPORT-IMPLEMENTATION-20260930.md` 脏改动。
