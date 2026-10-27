# 使用时长 UI 简化实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将使用时长页收敛为可分页的包概览、选中包的七桶分布和独立设备明细，同时把展示文本与分页元数据统一由后端提供，前端只负责映射、渲染和交互。

**架构：** 保留现有明亮主题和 `UsageDurationPanel` 单页入口。查询成功后，顶部显示服务端分页的包概览；下方固定显示当前选中包的两个 tab，`时长分布` 直接复用当前 summary 的七桶数据，`设备明细` 只有在切换到该 tab 或翻页时请求 devices API。draft scope 与 applied scope 分离，刷新/失败保留上一次成功结果，所有异步响应按 request id 隔离。

**技术栈：** FastAPI、SQLAlchemy async、Pydantic/JSON response、Vue 3 `<script setup>`、TypeScript、Vue Test Utils、Vitest、Pytest、真实 PostgreSQL 集成测试。

---

## 范围与视觉方向

### 视觉决策

- visitor mode：Operate；首要任务是比较包的使用时长并快速进入一个包的细节。
- 保留现有明亮 tokens，不引入新主题、新图表库或新字体。使用现有 `--panel-bg`、`--border-soft`、`--text-primary`、`--text-muted`、`--accent` 和错误/空状态 tokens。
- 视觉重点只放在“当前选中包”这一条上下文带：概览是安静、紧凑的表格；下方 tab 标题和选中包名承担方向感；不增加卡片墙、渐变或装饰性图表。
- 桌面采用单列纵向阅读：筛选 → 概览 → 选中包详情。窄屏继续纵向堆叠；表格只在内容确实超宽时横向滚动，设备分页栏必须位于滚动容器之外。
- 保持可见键盘 focus、`prefers-reduced-motion` 兼容和句式中文文案；错误文案说明下一步动作，空状态说明当前 scope 没有记录。

### 目标线框

```text
┌ 使用时长                                             ┐
│ 包名  日期  小时范围              查询   刷新        │
│ 已生效条件：……                                      │
├ 包概览 · 第 1 / N 页 · 每页 10/20/50                ┤
│ 包名 | 设备数 | 总时长 | 平均时长 | 最后上报 | 详情 │
│ rows …                                               │
│ 上一页                         下一页                │
├ com.example.app · 使用时长                         ┤
│ [时长分布] [设备明细]                               │
│  分布：7 行 interval / device count / share / total │
│  或设备：表格（滚动）                                │
│  分页栏（滚动容器外）                                │
└──────────────────────────────────────────────────────┘
```

## 文件清单与职责

- 修改：`backend/app/services/usage_duration_service.py`——为 summary/devices page envelope 增加 `total_pages`，保留全部现有数值字段，并生成统一展示文本；不改变最新记录、七桶边界、北京时间和 null 语义。
- 修改：`backend/app/api/admin/usage_duration.py`——保持现有 query 参数与 HTTP 路径，明确返回新 envelope 字段的兼容性；不新增数据库表、迁移或写入接口。
- 修改：`backend/tests/test_usage_duration_summary.py`——覆盖 `total_pages`、展示文本、null、七桶精度与页边界。
- 修改：`backend/tests/test_usage_duration_admin_api.py`——覆盖 API response contract、旧数值字段保留和展示字段存在。
- 修改：`backend/tests/test_usage_duration_postgres_integration.py`——用真实 PostgreSQL 比较改动前后数值/桶结果，检查分页元数据和展示字段不改变统计语义。
- 修改：`frontend/src/api/usageDurations.ts`——扩展 response 类型；保留现有数值字段，声明 `total_pages` 和后端展示字段。
- 修改：`frontend/src/components/UsageDurationPanel.vue`——重排为概览、选中包详情 tab、服务端分页和状态处理；前端不重新计算桶、百分比、总页数或业务时长文本。
- 修改：`frontend/src/components/UsageDurationPanel.test.ts`——先写失败测试，再覆盖 query 次数、分页、自动选中、tab 请求边界、刷新失败、乱序响应、窄屏结构和格式展示。
- 不修改：`backend/app/models/usage_duration.py`、数据库 schema、上传协议、解析任务、旧 `/api/admin/usage-durations` 写入/查询语义。
- 不修改：生产 release、生产数据库、systemd、Nginx；本计划通过 review 前不得实现、提交、推送、合并或部署。

### 数据契约

所有 page response 继续返回现有字段并新增：

```ts
type UsagePage<T> = {
  total: number;
  total_pages: number;
  page: number;
  page_size: number;
  items: T[];
};
```

Summary item 保留 `device_count`、`total_duration_s`、`average_duration_s`、`buckets`、`last_report_at` 等数值/既有字段，新增明确的展示字段：`total_duration_text`、`total_duration_exact_text`、`average_duration_text`、`average_duration_exact_text`、`last_report_text`。每个 bucket 保留 `count`、`share`、`total_duration_s`，新增 `interval_text`、`count_text`、`share_text`、`total_duration_text`、`total_duration_exact_text`。Device item 保留 `duration_s`、`last_report_at`、`os` 等字段，新增 `duration_text`、`duration_exact_text`、`last_report_text`。前端只能读取这些 text 字段；不得用 `Math`、`reduce`、排序或分钟换算重建业务值。

展示字段规则固定为：

- `null` 时长、平均值、时间和 share 显示 `-`，不显示 `0`；bucket `count=0` 必须显示 `0`，不能误转成 `-`。
- 后端保留 `duration_s` / `average_duration_s` 的原始数值精度，不把平均值强制转换为整数；使用 `Decimal(str(value))` 做展示舍入，避免二进制浮点尾数。主显示文本使用“X 小时 Y 分 Z 秒”或“Y 分 Z 秒”，小于 1 分钟显示“Z 秒”。精确秒值作为 `*_exact_text` 次级文本或 tooltip 提供，不由前端重算。整分钟省略秒段，整小时省略分钟段。
- `average_duration_text` 遵循同一主显示规则，按 1 秒四舍五入仅用于展示；`average_duration_s` 原值仍保留在 JSON 中，测试必须分别断言原值和文本。
- share 使用后端统一百分比精度，按 Decimal 四舍五入保留一位小数并带 `%`；`0` 为 `0.0%`，`null` 为 `-`。
- `last_report_text` 使用已有北京时间序列化口径，不在浏览器时区转换。
- `page_size <= 0` 必须先拒绝；`total_pages = 0 if total == 0 else ceil(total / page_size)`，非空结果至少为 1 页。空结果返回 `total=0`、`total_pages=0`，请求超出末页返回空 items 和准确元数据；空结果和越界页分别有测试。

## 任务 1：先建立后端展示与分页契约的失败测试

**文件：**
- 修改：`backend/tests/test_usage_duration_summary.py`
- 修改：`backend/tests/test_usage_duration_admin_api.py`
- 修改：`backend/tests/test_usage_duration_postgres_integration.py`

- [ ] **步骤 1：编写失败测试**

  在现有 `test_usage_summary_uses_only_latest_device_and_computes_seven_buckets_with_totals`（`backend/tests/test_usage_duration_summary.py:101`）中复用已有 `Db`、`Result`、`START`、`END` 名称：将 fake rows 改为包含两个返回页以内的 row、每行 `_total=3`，调用处明确使用 `db`、`package_name=None`、`range_start=START`、`range_end=END`、`page=2`、`page_size=2`、`sort_by="package_name"`、`sort_order="asc"`。对第一行设置 `total_duration_s=1500`、`average_duration_s=None`、第一个 bucket 的 `share=None`，然后断言 `total_pages == 2`、`total_duration_text == "25 分"`、`average_duration_text == "-"`、`share_text == "-"`、`interval_text == "≤120 秒"`。

  同一测试块再加入 `count=0 -> "0"`、`share=0 -> "0.0%"`、`share=None -> "-"`、Decimal 平均值原值不变、`os=None`/`last_report_at=None` 展示为 `-` 的断言。对 `page_size=0` 断言 ValueError/HTTP 422；对 `page > total_pages` 断言 `items=[]` 且 `total_pages` 不变。

  在现有 `backend/tests/test_usage_duration_summary.py` 的 devices 测试和 `backend/tests/test_usage_duration_admin_api.py::test_usage_duration_devices` 中断言 `total_pages`、`duration_text`、`last_report_text` 存在，同时 `duration_s`、`last_report_at`、`os` 原值不变。用现有 empty-page fixture 断言 `total=0` 时 `total_pages == 0`。API 测试必须验证旧字段仍在 response 中，而不是只检查新字段；新增字段缺失时的兼容解析规则也要有测试。

- [ ] **步骤 2：运行测试确认正确失败**

  运行：

  ```powershell
  python -m pytest -q backend/tests/test_usage_duration_summary.py backend/tests/test_usage_duration_admin_api.py
  ```

  预期：FAIL，失败原因必须是缺少 `total_pages` 或展示字段，不能是导入、路径或 fixture 错误。

- [ ] **步骤 3：补充真实 PostgreSQL 等价性测试**

  在 `backend/tests/test_usage_duration_postgres_integration.py` 使用现有临时 PostgreSQL fixture，固定同一组边界数据：120、121、300、301、899、900、1199、1200、1499、1500、`NULL` 平均值和同一设备同一时间的 id tie。对新 response 断言：

  - `device_count`、`total_duration_s`、`average_duration_s`、七桶 count/share/total duration 与改动前基线完全相等；
  - `total_pages` 只由 `total/page_size` 得出；
  - 展示文本来自相同数值，不改变北京时间或最新记录选择。

- [ ] **步骤 4：运行后端红灯集**

  运行：

  ```powershell
  python -m pytest -q backend/tests/test_usage_duration_summary.py backend/tests/test_usage_duration_admin_api.py backend/tests/test_usage_duration_postgres_integration.py
  ```

  预期：新断言先失败，现有旧断言失败数保持可解释；若出现数据库连接或路径错误，先修正测试环境再进入实现。

## 任务 2：实现最小后端 contract，保持统计语义不变

**文件：**
- 修改：`backend/app/services/usage_duration_service.py`
- 修改：`backend/app/api/admin/usage_duration.py`

- [ ] **步骤 1：实现统一格式化辅助函数**

  在 service 内使用一个纯函数处理秒数和一个纯函数处理 share；其输入只接受后端已经计算出的数值，输出 `text`，不改变 query。边界行为固定为：`None -> "-"`、`120 -> "2 分钟"`、`121 -> "2 分钟 1 秒"`、`0.3333 -> "33.3%"`。

- [ ] **步骤 2：为 summary/devices envelope 增加分页和展示字段**

  在现有 rows 映射处保留旧字段，追加新字段；用同一个 `total_pages(total, page_size)` 辅助函数实现 `page_size <= 0` 拒绝、否则 `0 if total == 0 else ceil(total / page_size)`。格式化函数必须用 Decimal 进行舍入。不要修改 `SUMMARY_BUCKETS`、latest rank、排序兼容参数或 SQL 聚合表达式。

- [ ] **步骤 3：运行后端测试确认通过**

  运行任务 1 的两个命令，预期所有相关测试通过；再运行：

  ```powershell
  python -m pytest -q backend/tests
  ```

  预期：完整后端测试保持通过，且无新增 warning。

- [ ] **步骤 4：Commit**

  仅在 review 放行并完成验证后提交：

  ```powershell
  git add backend/app/services/usage_duration_service.py backend/app/api/admin/usage_duration.py backend/tests/test_usage_duration_summary.py backend/tests/test_usage_duration_admin_api.py backend/tests/test_usage_duration_postgres_integration.py
  git commit -m "feat: add usage duration display contract"
  ```

## 任务 3：重做前端状态模型和概览分页

**文件：**
- 修改：`frontend/src/api/usageDurations.ts`
- 修改：`frontend/src/components/UsageDurationPanel.vue`
- 修改：`frontend/src/components/UsageDurationPanel.test.ts`

- [ ] **步骤 1：先写前端失败测试**

  在 `UsageDurationPanel.test.ts` 增加这些独立行为测试：

  1. 初次挂载只请求一次 summary，默认 page size 为 10；概览只渲染 6 个列标题，不渲染七桶列。
  2. summary 响应 `total_pages=3` 时，点击下一页只发送 `{ page: 2, page_size: 10 }`，并保留 scope；切换 50 后发送 page 1/page_size 50。
  3. summary 返回单个包时自动选中该包并渲染七个分布行；不调用 devices endpoint。summary 返回多包时 selected package 初始为空，必须点击“查看详情”后才选中。
  4. 多包返回时不自动请求 devices；点击“查看详情”只改变 selected package 和分布视图，不重复请求 summary。概览成功翻页或成功替换 scope 后清空旧 selected package/detail；只有刷新同 scope 当前页且新页仍包含原包时才允许保留 selection。
  5. 切换到 `设备明细` 才调用 devices endpoint；切 tab 不重复请求 summary；设备分页和 page size 50 都把分页栏放在横向滚动容器外的 DOM 结构中。
  6. draft scope 改动后未点击查询不改变 applied scope；查询失败保留旧 summary、selection、detail cache 和 applied scope；只有成功提交新 scope 才清空旧 selection/detail。成功翻页清 selection，若新页只有一个包则自动选中；刷新同 scope 当前页时，若原 selected package 仍在新结果中则保留并更新其分布但使设备明细 cache 失效，否则清空；刷新失败保留旧 rows/selection/detail 并显示错误。
  7. summary/devices request key 必须包含完整 scope、package、page、page_size 和 generation；用递增 request id 隔离过期响应，request id 只用于响应隔离，不假设实际取消了 HTTP 请求。两个 summary 请求和两个 devices 请求乱序返回时，旧响应不能覆盖新响应；卸载后响应不更新组件。
  8. 后端提供 `total_duration_text`、`average_duration_text`、`share_text`、`last_report_text` 时前端原样渲染；测试源码不得出现业务 `Math.round`、`Math.ceil`、`reduce` 或分钟换算。普通 UI 状态判断和比较不受此限制。
  9. 空 summary 显示空状态且不显示选中包详情；API error 显示可重试错误。

- [ ] **步骤 2：运行前端红灯测试**

  运行：

  ```powershell
  npm test -- --run src/components/UsageDurationPanel.test.ts --reporter verbose
  ```

  预期：新测试因当前横向七桶概览、行内展开模型和缺少 `total_pages` 而失败；若测试先通过，必须修改断言使其准确覆盖尚未实现的行为。

- [ ] **步骤 3：更新 API 类型，不改变请求路径**

  将 `UsagePage<T>` 扩展为包含 `total_pages`；summary item、bucket、device item 增加可选/必需的展示字段并保留现有数值字段。请求函数继续使用 `/usage-durations/summary` 和 `/usage-durations/devices`，不新增预取接口。

- [ ] **步骤 4：实现最小状态模型**

  在组件内保留 `draft`/`appliedScope` 分离，新增明确的 `summaryPage`、`summaryPageSize`、`selectedPackage`、`detailTab`、`detailPage`、`detailPageSize` 和 `generation`。request key 使用完整 scope/package/page/page_size/generation；过期 response 只按 request id 丢弃。查询失败不清 selection/detail/applied；成功提交新 scope 才清空，成功 overview 翻页清空；成功刷新同 scope 当前页时，若原包仍在返回结果中则保留 selection、更新 bucket 并清空 devices cache，否则清空。只有有效单包结果自动选中。tab 切换不触发 summary；设备 tab 首次进入才请求 devices。

- [ ] **步骤 5：实现概览与详情模板**

  概览列固定为：包名、设备数、总时长、平均时长、最后上报、详情。详情按钮设置 selected package。分布 tab 将 `selectedPackage.buckets` 映射成七行，列固定为 interval、device count、share、bucket total duration；使用后端 text 字段。设备 tab 包含 device id、机型、OS、最新时长、SDK 版本、应用版本、最后上报共 7 列；分页栏置于 `.detail-table-scroll` 外。

- [ ] **步骤 6：实现错误、空态和响应隔离**

  summary/devices 请求 key 以完整 `{scope,package,page,page_size,generation}` 组成，并以递增 request id 丢弃旧响应；request id 只负责响应隔离，不假设 HTTP 请求已取消。刷新不清空已有成功结果；失败只更新错误提示。查询失败不更新 applied scope；查询成功才更新。devices 请求同样按完整 key 隔离，旧设备响应不能覆盖新 tab/页。

- [ ] **步骤 7：补充移动样式和可访问性**

  复用现有明亮 tokens；在 `max-width: 720px` 下筛选、概览、详情纵向堆叠，按钮可换行，表格容器允许横滚，分页栏不被表格滚动截断。tab 使用按钮、具有 active/`aria-selected` 状态；详情按钮有明确文本；保留现有 focus ring 和 reduced-motion 规则。

- [ ] **步骤 8：运行前端测试并重构**

  运行：

  ```powershell
  npm test -- --run src/components/UsageDurationPanel.test.ts --reporter verbose
  npm test -- --run
  npm run build
  ```

  预期：组件专项和全量测试通过，生产构建成功；只有在绿灯后提取分页/格式化的非业务 UI 辅助函数。

## 任务 4：真实 PostgreSQL 与本地 API 验收

**文件：**
- 不新增业务代码；使用现有 `backend/tests/test_usage_duration_postgres_integration.py`、本地快照服务和现有性能证据脚本。

- [ ] **步骤 1：执行真实 PostgreSQL 新旧数值等价检查**

  在隔离测试库插入同一组边界样本，分别运行基线查询和新实现，逐字段比较 summary/device numeric fields、七桶 count/share/total duration、最新北京时间和总数；只允许新增 display text/`total_pages` 差异。

- [ ] **步骤 2：验证 API 请求次数**

  使用前端 Vitest mock 和本地 Admin API 只读请求确认：

  - 查询一次只产生一次 summary 请求；
  - summary 翻页只请求 summary；
  - 分布 tab 不请求 devices；
  - 设备 tab/设备翻页只请求 devices；
  - refresh 只请求当前 summary，不预取设备；
  - package/scope 改变后 detail page 回到 1。

- [ ] **步骤 3：执行本地 HTTP 只读检查**

  保持现有本地 PostgreSQL、Admin API 和 Vite 服务运行，使用已有本地凭据但不在输出中打印密码/Token。验证一条有数据 scope、一条空 scope、一条超过 50 台设备的 package，记录 HTTP 状态、`total_pages`、items 数量和展示字段精度。

- [ ] **步骤 4：运行最终门禁**

  ```powershell
  python -m pytest -q backend/tests
  npm test -- --run
  npm run build
  git diff --check
  git status --short --branch
  ```

  预期：后端、前端、构建和 diff 检查全部通过；用户既有 dirty 文件与 `.local-run/` 未被修改；本地服务仍监听原端口。生产仍不部署。

## 任务 5：评审与交付边界

- [ ] **步骤 1：先停止在计划阶段等待 review**

  将本文件绝对路径交给 root/review：

  `C:\Users\喻远飞\.codex\worktrees\ef23\SDK\docs\superpowers\plans\2026-10-27-usage-ui-simplification.md`

  在收到明确放行前，不执行任务 1–4 的实现步骤，不提交、不推送、不合并、不 SSH、不部署。

- [ ] **步骤 2：review 放行后的执行方式**

  仅在 root 明确放行后，使用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 按任务顺序实施；每个行为遵循 TDD 红灯 → 最小实现 → 绿灯 → 重构，且先完成后端契约再完成前端消费。

- [ ] **步骤 3：最终生产边界**

  本计划本身不授权生产操作。生产部署必须另有明确用户指令，并重新执行发布前测试、真实 PostgreSQL 等价性、备份、健康检查和回滚证据收集。

## 计划自检

- 覆盖了 overview 6 列、服务端 10/20/50 分页、独立双 tab、七桶七行、单包自动选中、设备 tab 才请求、OS 七列、横滚外分页、后端展示文本/`total_pages`、draft/applied、刷新留旧数据、错误恢复、乱序隔离、移动纵向和无新图表库。
- 覆盖了真实 PostgreSQL 数值等价、空页、空结果、分页边界、格式精度、UI 调用次数和错误态验收。
- 没有把七桶、share、总页数或时长格式化业务计算留给前端。
- 没有要求修改上传协议、数据库 schema、解析任务或生产配置。
- 当前未实现任何计划中的业务代码；计划完成后等待评审。
