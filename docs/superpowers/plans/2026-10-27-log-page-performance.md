# 日志与使用时长页面性能优化实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在不改变筛选语义、导出绑定、latest 设备规则和现有 API 兼容性的前提下，降低原始日志候选/列表和使用时长汇总的响应时间，并补齐当前使用时长设备明细的 OS 展示。

**架构：** 以生产主线 `79aef8cceac23682cee6bb7ee18e9dc991e6d5c3` 为实现基线。包名候选从已存在的 `sdk_package_catalog` 读取；SDK 版本按有效包名分 key 做短 TTL、有界缓存和同 key 请求合并。原始日志列表保留精确 count，通过单次 SQL 返回页面与精确总数；使用时长汇总在同一查询中复用 latest 设备集合，空页时才补做精确 total 查询。生产只读诊断结果不作为验证替代，所有性能结论以本地真 PostgreSQL 快照的重复样本 p50/p95 为准。

**技术栈：** Python 3.11、FastAPI、SQLAlchemy async、PostgreSQL、pytest；Vue 3、TypeScript、Vitest、Vite。

---

## 文件职责

- 修改 `backend/app/services/analysis_service.py`：目录包名候选、SDK 版本查询、短 TTL 缓存和同 key 请求合并；保留旧 `filter-options` 响应字段。
- 修改 `backend/app/services/usage_duration_service.py`：汇总查询复用 latest 集合，保持 count、分页、排序、七桶和占比语义。
- 修改 `backend/app/services/analysis_service.py`：以单次精确窗口查询返回日志页面与总数。
- 修改 `backend/app/api/admin/usage_duration.py`、`backend/app/services/usage_duration_service.py`：设备明细响应补充已有 `os` 字段。
- 修改 `frontend/src/api/usageDurations.ts`、`frontend/src/components/UsageDurationPanel.vue`：设备明细展示 OS，并支持默认 10、可选 20/50 的分页，不增加 OS 筛选或导出。
- 修改对应后端测试：验证目录读取、缓存 key/TTL/合并、精确 count、usage 空页与排序语义、OS 响应。
- 修改对应前端测试：验证设备明细 OS 展示、加载/取消过期结果和现有 scope/export 绑定不变。
- 创建 `scripts/benchmark_log_page_performance.py` 或复用现有测试辅助：对同一 PostgreSQL 快照、同一参数重复测量空包/指定包、短窗/最大合法范围、空结果/深页，输出样本数、p50、p95 和 SQL 统计；不得连接生产。

## 主线与工作区基线

- [ ] 核对 `git rev-parse HEAD` 为 `726e3ae526391b8c6cd1d7cbc8fef539d4b136b5`，核对主线对象 `79aef8cceac23682cee6bb7ee18e9dc991e6d5c3` 存在。
- [ ] 记录并保留既有 dirty：`docs/50-LOG-METRICS-DEVICE-DURATION-H1-EXPORT-IMPLEMENTATION-20260930.md`、`.local-run/`、`backend/tests/test_admin_auth.py`；不覆盖、不删除、不纳入本次提交。
- [ ] 将 `79aef8cceac23682cee6bb7ee18e9dc991e6d5c3` 合并到 feature worktree，确认无冲突后记录新的实现基线 SHA。

## 任务 1：先建立失败测试与本地快照基线

**文件：**

- 修改：`backend/tests/test_analysis_service.py`
- 修改：`backend/tests/test_usage_duration_service.py` 或对应现有测试文件
- 修改：`backend/tests/test_usage_duration_api.py`
- 修改：`frontend/src/components/UsageDurationPanel.test.ts`
- 创建或修改：`scripts/benchmark_log_page_performance.py`

- [ ] **步骤 1：编写失败测试。** 添加以下行为断言：
  - `get_event_filter_options()` 的包名来自目录服务，且旧响应仍同时包含 `package_names` 与 `sdk_versions`。
  - 相同有效包名的版本查询共享一次 in-flight 请求；不同包名不共享；TTL 到期后重新查询。
  - 日志列表的页面查询返回精确 `total`，深页和空页不改变 total。
  - usage summary 的结果仍按每个 `(package_name, device_id)` 的最新记录累计，七桶、占比、总时长、排序和空页 total 不变。
  - usage devices item 包含 `os`，前端展开明细显示 OS。
- [ ] **步骤 2：运行目标测试确认红灯。**
  运行：`python -m pytest -q backend/tests/test_analysis_service.py backend/tests/test_usage_duration_service.py backend/tests/test_usage_duration_api.py`
  运行：`npm run test -- --run frontend/src/components/UsageDurationPanel.test.ts`
  预期：新增断言因生产代码尚未实现而失败；若先因导入或 fixture 错误失败，先修正测试本身，不改生产代码。
- [ ] **步骤 3：建立本地真 PostgreSQL 快照基线。** 使用已有测试数据库配置或本地快照，禁止使用生产连接；为候选、日志列表、usage summary 分别记录相同参数的至少 10 次样本数、p50、p95、计划和行数/结果摘要。

## 任务 2：包名目录、SDK 版本缓存和候选接口

**文件：**

- 修改：`backend/app/services/analysis_service.py`
- 修改：`backend/tests/test_analysis_service.py`
- 修改：`backend/tests/test_admin_api.py`（仅当路由契约需要补充）

- [ ] **步骤 1：实现最小目录读取。** 使用现有 `package_catalog_service.search_packages(..., source="log")` 读取所有包名；有效包名经过现有归一化规则后作为 SDK 版本缓存 key。不得删除 `package_names` 或 `sdk_versions` 响应字段。
- [ ] **步骤 2：实现版本查询缓存。** 为 SDK 版本查询设置短 TTL `5_000ms`、最大条目数 `64`；缓存 key 必须包含有效包名，空包名使用独立 key。缓存值只保存版本列表和过期时间；同 key 正在执行时复用同一个 task；不同 key 并行执行。明确行为：新版本最多延迟 5 秒可见，手动刷新和导出接口不使用该缓存。
- [ ] **步骤 3：运行新增单测确认通过。**
  运行：`python -m pytest -q backend/tests/test_analysis_service.py backend/tests/test_admin_api.py`
  预期：新增缓存、key、TTL、目录来源测试通过。
- [ ] **步骤 4：运行本地快照候选基准。** 仅当目录候选 p50/p95 显著低于当前约 2 秒、且指定包版本不回退时保留该实现；否则回退无效改动并记录原因。

## 任务 3：原始日志精确 count 与分页

**文件：**

- 修改：实际承载 `get_events` 的 `backend/app/services/analysis_service.py`
- 修改：`backend/tests/test_analysis_service.py` 或 `backend/tests/test_admin_api.py`
- 修改：`scripts/benchmark_log_page_performance.py`

- [ ] **步骤 1：编写 SQL 语义失败测试。** 覆盖无结果、第一页、深页、日期/小时/包名/版本/日志级别过滤，断言 `total` 是精确匹配行数，items 与原实现一致。
- [ ] **步骤 2：实现单次精确查询候选。** 优先用 `count(*) over()` 与页面查询同一过滤关系返回精确 total；当深页或空页无行时补一次精确 count。不得使用估算值、隐式日期上限或未经授权的过滤。
- [ ] **步骤 3：运行红绿测试。**
  运行：`python -m pytest -q backend/tests/test_analysis_service.py backend/tests/test_admin_api.py`
  预期：分页、空页、过滤和精确 total 全部通过。
- [ ] **步骤 4：在同一 PostgreSQL 快照上比较执行计划与样本。** 只保留确实降低重复扫描且语义逐项一致的实现；若单次窗口查询不降低 p95，则保留原查询并记录“未入选”，不为达标强行改写。

## 任务 4：usage summary 复用 latest 集合

**文件：**

- 修改：`backend/app/services/usage_duration_service.py`
- 修改：`backend/tests/test_usage_duration_service.py`
- 修改：`backend/tests/test_usage_duration_admin_api.py`
- 修改：`scripts/benchmark_log_page_performance.py`

- [ ] **步骤 1：补齐失败回归测试。** 使用多个设备、多条上报、不同设备模型、空结果和深页，断言仍按每个设备最新记录计算，且总数、七桶、占比、排序、空页 total 与旧语义一致。
- [ ] **步骤 2：实现单查询复用。** 将 latest 设备集合构造成一次 grouped 查询，并在同一结果中携带精确 total；正常页不再单独重算 count，空页才执行精确 count。不得改为直接 sum 原始上报、按机型拆分、改变日期/小时过滤位置或 latest 规则。
- [ ] **步骤 3：运行后端测试。**
  运行：`python -m pytest -q backend/tests/test_usage_duration_service.py backend/tests/test_usage_duration_admin_api.py`
  预期：全部通过。
- [ ] **步骤 4：在真 PostgreSQL 快照重复测量。** 覆盖全部包名/指定包、短窗/最大 31 天合法范围、空结果/深页，输出至少 10 次样本 p50/p95；指定包不得回退，全部包名必须有明确改善证据，否则不宣称达标。

## 任务 5：usage devices OS 展示

**文件：**

- 修改：`backend/app/services/usage_duration_service.py`
- 修改：`backend/tests/test_usage_duration_api.py`
- 修改：`frontend/src/api/usageDurations.ts`
- 修改：`frontend/src/components/UsageDurationPanel.vue`
- 修改：`frontend/src/components/UsageDurationPanel.test.ts`

- [ ] **步骤 1：编写失败测试。** 断言 `/usage-durations/devices` item 返回已有 `os`，并断言展开的设备明细支持超过 10 条、最后一页、切换 20/50、上一页/下一页、包名/日期变化重置页码、失败后可重试；缓存 key 必须包含 scope、包名、page 和 page_size，过期响应不能覆盖新请求；不添加 OS 筛选、导出或日志 schema 字段。
- [ ] **步骤 2：实现最小响应和 UI 改动。** 从现有 `SdkUsageDuration.os` 透传到 devices item，在当前明亮风格表格中增加 OS 列；API 保留精确 `total`，前端默认 `page_size=10`，提供 10/20/50，按已生效包名和时间范围分页，筛选变化重置页码；缓存 key 包含 `scope+package+page+page_size`，保留取消过期结果、错误保留旧结果、scope 和导出绑定。
- [ ] **步骤 3：运行前后端测试。**
  运行：`python -m pytest -q backend/tests/test_usage_duration_api.py backend/tests/test_usage_duration_admin_api.py`
  运行：`npm run test -- --run frontend/src/components/UsageDurationPanel.test.ts`
  预期：OS 断言通过，现有行为无回归。

## 任务 6：集成验证、代码评审和交接

- [ ] **步骤 1：运行完整后端和前端测试。**
  运行：`python -m pytest -q backend/tests`
  运行：`npm run test -- --run`
  运行：`npm run build`
- [ ] **步骤 2：运行本地 PostgreSQL 真库一致性与性能基准。** 输出 SQL 结果逐项一致、样本数、p50/p95、候选最大延迟 5 秒缓存说明、usage 全包和指定包结果。
- [ ] **步骤 3：执行 `git diff --check` 与 `git status --short`。** 确认只包含本计划文件和实现/测试文件，不纳入既有 dirty。
- [ ] **步骤 4：请求代码评审。** 提供基线 SHA、HEAD SHA、计划路径、测试结果和性能报告；Critical/Important 问题修复后再继续。
- [ ] **步骤 5：生产保持只读。** 不执行迁移、回填、发布或服务重启；将最新实现 SHA、生产诊断 SHA、测试和性能证据交给 root 放行。
