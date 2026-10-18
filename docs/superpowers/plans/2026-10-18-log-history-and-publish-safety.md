# 日志检索、历史解析与配置发布确认实施计划

> **面向执行窗口：** 使用 superpowers:executing-plans 逐任务执行，阶段间由独立审查窗口验收。用户已指定实施窗口使用 gpt-5.6-luna、中等推理；主会话只负责方案和审查。

**目标：** 实现可搜索包名、固定历史解析结果、时长标签状态保留及配置发布预览确认。

**架构：** 复用已有包名搜索和已完成任务 stage 明细，通过 job_id 限定历史指标源；独立历史列表组件控制结果选择；发布使用客户端未保存检查与服务端保存时间并发校验。

**技术栈：** Vue 3、TypeScript、Vitest、FastAPI、SQLAlchemy、PostgreSQL。

**规格：** `docs/superpowers/specs/2026-10-18-log-history-and-publish-safety-design.md`。

## 0. 基线与隔离

- [ ] 验证基线 `6810fbd49ffefc641ca696d3664d263ea6f0fbcb`；创建独立分支 `codex/log-history-publish-safety-20261018` 和对应隔离 worktree，保留旧已验收分支及主仓库 dirty 文件。
- [ ] 检查适用 AGENTS.md；复制主会话已评审的本规格/计划到新 worktree 并提交文档。不读取或打印生产秘密，不合并推送部署。
- [ ] 记录依赖路径、现有本地服务 PID/工作目录。需要运行新候选时精确切换本次自有服务，使用独立本地库，保持已存在数据。

## 1. 可搜索包名组件

文件：新建 `frontend/src/components/PackageSelect.vue` 及 `.test.ts`；修改 `PackageMultiSelect.vue`、`LogAnalysisFilters.vue`、`LogViewer.vue`、`LogExportPanel.vue` 和各自测试；复用 `frontend/src/api/logExports.ts`。

- [ ] 先补行为测试：打开加载候选、搜索/空结果/错误重试、旧响应不得覆盖、单选完整包名、多选去重/删除、Escape/Enter、原始日志 SDK 版本重置。
- [ ] 实现统一单选/多选搜索基础组件或让已有多选使用同一候选加载逻辑；300ms debounce、有界返回；卸载后忽略响应。
- [ ] 接入解析必填单选、原始日志全部/单选及导出多选；单包导出沿用已生效包名，保留全部筛选 payload。
- [ ] 导出父筛选双向切换测试：单包→全部清空继承和旧多选；全部→单包仅发送新单包；A→B仅发送B；尚未应用的草稿筛选不影响payload。
- [ ] 执行相关组件/API测试，确认新失败用例转绿后提交。

## 2. 历史任务与固定结果服务

文件：`backend/app/api/admin/log_metrics.py`、`backend/app/services/log_parse_job_service.py`、`backend/app/services/log_metrics_service.py`；新建 `backend/app/services/log_history_service.py`、`backend/tests/test_log_history.py`，扩展现有 metrics/job 测试。

- [ ] 检查所有 stage 清理入口和成功任务 claim 条件；记录 h1_count/failed_h1_count 的实际含义，完整性判断与其一致，不臆造计数公式。
- [ ] 添加历史列表服务：包名精确筛选、created_at/id 倒序、page=1/page_size=10、上限50；返回元信息和结果是否可用，不在列表逐任务执行完整聚合。
- [ ] 将 metrics 查询的数据源参数化，默认仍是正式 H1/click，历史模式使用两张 stage 并对所有分支加 job_id。保留原统计计算代码，避免复制两套公式。
- [ ] 查询上下文显式包含H1模型/click模型/job_id，逐项检查overview全部scalar子查询、attempt_counts/mismatch、target helper、configs/failures/H1和关联click。SQL/服务层捕获每条历史SQL，断言stage job_id绑定以及无正式表引用；未知/非成功/不完整任务不允许fallback。
- [ ] 实现规格中的完整性不变量：processed=total；H1/failed计数；distinct H1事件+no_h1=processed；每个成功H1的click数与decoded_payload.planned_click_attempts数组长度相符且无孤立click。不能以declared_click_count代替click计数，不能把total=0与证据丢失混淆；旧格式缺证据明确不可用。失败H1留明细，成功聚合仍只计status=success。
- [ ] 新增明确的历史 metrics 路由，先验证任务成功与数据完整性；由 job 元信息决定 package/range/snapshot。未知任务404、未完成或缺失历史409；合法零结果200。
- [ ] 在本地 PostgreSQL 构造任务 A/B 相同包名范围但 H1/click 结果不同：B 发布覆盖正式结果后，A 历史所有 API仍读A；覆盖 failures/H1关联click、跨包隔离、零H1、不完整旧任务；成功任务不能被再次写入。
- [ ] 运行原有 metrics/job 回归，提交后交独立审查再继续历史 UI。

## 3. 历史结果 UI

文件：新建 `frontend/src/components/LogParseHistory.vue` 及测试；修改 `frontend/src/api/logMetrics.ts`、`frontend/src/views/LogViewer.vue`、`frontend/src/components/LogMetricsPanel.vue`、失败抽屉请求与测试。

- [ ] 添加类型明确的历史列表及历史五类指标 API。
- [ ] 默认折叠、展开懒加载、每页10条；筛选依据当前生效包名，日期不强制近三天；完整展示任务范围和状态。
- [ ] 当前结果/历史结果用独立 selection 状态；历史任务选中后全部指标和抽屉统一使用 job_id，禁止当前任务轮询覆盖历史视图。
- [ ] 测试两任务快速切换迟到响应、返回当前结果、创建任务/应用查询退出历史、失败任务不可误显示成功结果、历史加载失败不显示上一个任务数据。
- [ ] 本地浏览器用两条不同成功任务演示；提交。

## 4. 使用时长状态保留

文件：`frontend/src/views/LogViewer.vue`、`frontend/src/components/UsageDurationPanel.vue` 及测试；只读参考 `backend/app/services/usage_duration_service.py`。

- [ ] 添加行为测试：首次进入1次summary，切走再回仍1次且筛选/明细保留，刷新增1次，新条件查询增1次。
- [ ] 对时长组件懒创建后保留实例；不提前加载，不因此启动原始日志或解析结果的隐藏轮询。
- [ ] 显示最近成功读取时间；刷新保留旧结果并标识加载状态，失败明确保持旧条件数据，不伪装为新查询结果。
- [ ] 验证七桶与累计时长计算无差异；记录默认全部包生产4.1156秒仅一次样本，不能报告缓存已优化首屏SQL。提交。

## 5. 发布预览与原子版本检查

文件：`frontend/src/views/ConfigManager.vue`、`frontend/src/api/config.ts`、相关 types/tests；`backend/app/api/admin/config_mgr.py`、`backend/app/services/config_service.py`、`backend/app/schemas/admin_schemas.py`、`backend/tests/test_config_service.py`、`backend/tests/test_encrypted_config_service.py`，新增 `backend/tests/test_config_publish_precondition.py`。

- [ ] 补测试：JSON/树/change_log未保存禁止publish；仅缩进/键序不同不阻止；无效JSON阻止；取消预览无POST；三文件预览均来自GET结果。
- [ ] 保存已确认服务器内容为基准，使用递归对象键排序且保留数组顺序的语义比较。保存超时仅确认时间变化不等于当前编辑内容已存储，必须读回核对内容后更新基准。
- [ ] 实现预览态：冻结config_id/updated_at，右侧只读展示三份JSON，确认与取消；确认前禁切版本/禁编辑，标题显示包名与保存时间。
- [ ] publish body新增可选 expected_updated_at（带时区datetime，旧无body API兼容）；网页始终发送。定义冲突异常映射409。
- [ ] expected_updated_at=None只代表旧API客户端兼容路径，新增网页确认请求不得省略；测试断言网页请求体携带预览值。
- [ ] 在包级锁内重新锁定/刷新配置行并检查expected_updated_at和draft，检查必须在COS、版本分配、状态写入之前；保存使用行锁并重新检查状态。避免锁前读取的ORM缓存值成为比较依据。
- [ ] 本地PostgreSQL双会话测试：预览后保存导致409且无版本/上传副作用；发布取得锁后保存等待并因非draft拒绝；不同草稿发布无锁顺序反转；legacy publish兼容；保留60秒与超时复核。
- [ ] 运行配置加密、版本分配、发布回滚回归，提交并交审查。

## 6. 集成验收与交付

- [ ] 文档记录接口、历史不可用提示、发布操作、生产性能观察与尚未验证部分。
- [ ] 后端：`python -m pytest backend/tests -q`（先设置工作区PYTHONPATH及专用本地测试DB）；不得指向生产。
- [ ] 前端：在 frontend 执行 `npm test -- --run --pool=threads --poolOptions.threads.singleThread=true`、`npm run build`；使用已验证bundled Node，避免默认并发OOM。
- [ ] 验证 `git diff --check`；冻结最终SHA，独立验收窗口核对源码/证据一致，保留错误修复后的真实测试数量。
- [ ] 真实浏览器验证桌面和390px，搜索弹层可见/键盘可用，历史结果只切换原结果区，发布右侧预览及取消完整，标签切换不重复请求。
- [ ] 本地服务持久隐藏启动，跨回合复核端口及真实模块/受保护API；只链接私有凭据文件，不输出秘密。提交最终操作与验收记录，报告SHA；等待后续单独的合并/部署指令。
