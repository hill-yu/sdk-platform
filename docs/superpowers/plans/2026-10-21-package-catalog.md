# 包名目录实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 增加按包名唯一的 PostgreSQL 目录，分别记录是否存在原始日志和使用时长数据，让两个管理端下拉查询不再扫描按月分区的大表，同时保持历史 API 的搜索、排序和 limit 语义。

**架构：** 新增 `sdk_package_catalog`，主键为 `package_name`，字段 `has_log`、`has_usage`、`created_at`、`updated_at`。`POST /api/v1/log` 和 `POST /api/v1/usage-duration` 在写入事实表的同一事务中，对本请求涉及的 distinct 包名先做主键查询；已有所需来源标记时直接返回，不更新目录行，只有缺包或缺来源时才执行带变化条件的 `INSERT ... ON CONFLICT DO UPDATE`。不使用进程缓存，因此不会吞掉回滚，也能在多实例下正确合并来源标记。历史补齐使用可重跑、按 `(server_ts,id)` 游标分批的脚本；每批使用 `ON CONFLICT` 的布尔 OR 合并，补齐期间的新写入不会把已有来源标记覆盖掉。

**技术栈：** PostgreSQL 分区表、SQLAlchemy async、FastAPI、Alembic 之外的现有 `scripts/*.sql`/Python 迁移约定、pytest、真实 PostgreSQL snapshot（约 54,025 条事件、47,596 条 usage）。

---

## 设计决策与不变量

- 目录列：`package_name VARCHAR(255) PRIMARY KEY`、`has_log BOOLEAN NOT NULL DEFAULT FALSE`、`has_usage BOOLEAN NOT NULL DEFAULT FALSE`、`created_at TIMESTAMPTZ NOT NULL DEFAULT now()`、`updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`。
- “原始日志”只对应 `sdk_events.event_type = 'log'`；点击事件不设置 `has_log`，因为当前 `/log-packages` 的旧查询也只筛选 `event_type='log'`。
- `/api/admin/log-packages` 只筛 `has_log = TRUE`；`/api/admin/usage-package-names` 只筛 `has_usage = TRUE`。关键字仍为去首尾空白后的大小写不敏感包含匹配，仍按包名升序、仍使用原 limit；空关键字也只读目录。
- 目录更新必须和事实表写入共用同一个 `AsyncSession` 事务。事实写入失败或目录 upsert 失败时全部回滚；不接受“事实成功、目录失败”的静默降级。
- 日志批次只处理一次 distinct 包名；对已具备 `has_log` 的包不写目录，对缺包/缺来源的包才执行一次条件 upsert，不按每条日志写目录；usage 请求同理。`DO UPDATE` 必须带“目标 flag 仍为 false 且 excluded flag 为 true”的 `WHERE`，避免热门包每次上传争用同一行、刷新 `updated_at` 或产生无效 UPDATE。该额外成本不在 SDK 热路径之外引入网络调用、缓存失效或后台依赖。
- 读取切换必须有显式目录读取开关，默认值为旧事实表查询；这不是异常自动 fallback。发布门控顺序固定为：schema migration → 部署新 writer（读取仍旧）→ 确认旧 writer 已排空 → 从头执行受控 final backfill → 对账两方向差集为空 → 手动启用目录读取；稳定后保持目录读取开启。
- 搜索迁移必须启用 `pg_trgm` 并创建目录搜索索引；服务代码不保留扫描事实表的 fallback。验证 SQL 必须证明查询计划不访问 `sdk_events` 或 `sdk_usage_durations`。
- 历史补齐以 `(server_ts, id)` 游标排序分批，设置 statement timeout，失败可从上次游标重跑；checkpoint 只有在该批事务 commit 成功后才推进，崩溃时允许重放最后一批，绝不能跳过。由于晚提交写入可能带有较早 `server_ts`，最终 pass 必须在所有旧 writer 排空后从头执行，不能只依赖历史 checkpoint。初次补齐、writer 上线后的 reconciliation、旧 writer 排空后的从头 final pass、两方向差集和最终计数校验组成发布门槛。
- 回滚只回滚应用代码/查询路径；目录表和索引为 additive，不删除事实数据。若目录代码需要撤回，旧查询仍可临时恢复，但发布流程不得把这作为静默 fallback；目录表保留供再次补齐。

## 文件清单

- 创建：`scripts/migrate_package_catalog.sql` —— 幂等创建目录、`pg_trgm` 扩展、搜索索引和注释。
- 修改：`scripts/init_db.sql` —— 新数据库初始化时创建相同目录和索引。
- 创建：`scripts/backfill_package_catalog.py` —— 真实 PostgreSQL 的游标分批补齐、超时、进度、重跑和最终校验。
- 创建：`backend/app/models/package_catalog.py` —— SQLAlchemy 目录模型。
- 修改：`backend/app/models/__init__.py` —— 导出模型，确保元数据和测试可发现。
- 创建：`backend/app/services/package_catalog_service.py` —— distinct 包名来源 upsert 与目录搜索查询，集中保持来源语义。
- 修改：`backend/app/core/config.py` —— 增加显式 `PACKAGE_CATALOG_READS_ENABLED` 配置，默认 `false`，仅用于迁移门控，不承担异常 fallback。
- 修改：`backend/app/api/sdk/log.py`、`backend/app/api/sdk/usage_duration.py` —— 在事实表写入同一 session 中调用目录 upsert。
- 修改：`backend/app/services/log_export_service.py`、`backend/app/api/admin/log_exports.py` —— 两个旧 API 改读目录，保留 envelope、排序和 limit。
- 测试：`backend/tests/test_package_catalog_service.py` —— SQL 语义、来源 OR 合并和查询边界。
- 测试：`backend/tests/test_package_catalog_migration.py`、`scripts/test_backfill_package_catalog.py` —— 迁移幂等性、游标批次、超时/重跑契约。
- 修改/新增集成测试：`backend/tests/test_log_export_api.py`、`backend/tests/test_sdk_api.py`（以仓库实际现有 SDK API 测试文件为准）——写入后同事务目录可见、失败回滚、多来源标记。
- 修改：`docs/03-DATABASE.md`、`docs/07-DEPLOYMENT.md` —— 目录结构、上线顺序、回滚和 reconciliation 操作记录。

## 任务 1：先写迁移和模型契约测试

**文件：** `scripts/migrate_package_catalog.sql`、`scripts/init_db.sql`、`backend/app/models/package_catalog.py`、`backend/app/models/__init__.py`、`backend/tests/test_package_catalog_migration.py`。

- [ ] 编写失败测试，断言迁移包含 `CREATE TABLE IF NOT EXISTS sdk_package_catalog`、两项 boolean 默认值、主键、`updated_at`、`pg_trgm` 和目录搜索索引；断言初始化脚本包含同等结构。
- [ ] 编写模型测试，断言列名、长度、非空、默认值和 `package_name` 主键与 SQL 一致。
- [ ] 运行：`cd backend; pytest -q tests/test_package_catalog_migration.py`；预期先因文件/模型不存在失败。
- [ ] 实现幂等 SQL。目录查询需要一个普通 `(package_name)` 索引或两个来源 partial B-tree 索引支持空关键字排序，并需要 `GIN (package_name gin_trgm_ops)` 支持包含搜索；扩展不存在时迁移明确失败，不允许隐式退回全表扫描。
- [ ] 运行同一测试并提交：`git add scripts/migrate_package_catalog.sql scripts/init_db.sql backend/app/models backend/tests/test_package_catalog_migration.py && git commit -m "feat(db): add package catalog schema"`。

## 任务 2：实现同事务目录 ensure 与搜索服务

**文件：** `backend/app/services/package_catalog_service.py`、`backend/tests/test_package_catalog_service.py`。

- [ ] 先写失败测试：同一包名分别标记 `has_log`/`has_usage` 时必须 OR 合并；重复 ensure 不清除已有标记且不产生 UPDATE；一次日志批次生成一次 distinct 包名 ensure；搜索只能带来源 flag、关键字包含匹配、升序和 limit。
- [ ] 运行：`cd backend; pytest -q tests/test_package_catalog_service.py`；预期先因服务不存在失败。
- [ ] 实现 `ensure_package_sources(db, package_names, *, has_log=False, has_usage=False)`：去空白、去重；先按主键批量读取现有 flag，仅保留“缺包或缺所需来源”的包；对剩余包使用 `pg_insert(PackageCatalog).values(...)`，冲突更新使用 flag OR，并设置 `updated_at`；`DO UPDATE ... WHERE` 仅在实际 flag 从 false 变 true 时成立。该函数只使用传入 session，不自行 commit。测试必须证明重复请求不产生 UPDATE，且不同实例并发同包/不同来源后两 flag 都为 true。
- [ ] 实现 `search_packages(db, keyword, limit, source)`：只查询目录模型；`keyword.strip()` 后使用 `ilike('%...%')`；按 `package_name` 升序 `limit(limit)`；`source` 只允许 `log`/`usage`，未知来源在内部抛出明确错误。
- [ ] 运行测试并提交：`git add backend/app/services/package_catalog_service.py backend/tests/test_package_catalog_service.py && git commit -m "feat(db): add transactional package catalog service"`。

## 任务 3：接入 SDK 写路径，避免每条日志重复写

**文件：** `backend/app/api/sdk/log.py`、`backend/app/api/sdk/usage_duration.py`、对应 SDK API 集成测试。

- [ ] 先写失败集成测试：日志批次写入事实表后目录 `has_log=true`；usage 写入后 `has_usage=true`；同包两来源都为 true；模拟目录 upsert 异常时事实写入回滚；日志批次含重复包名时目录 upsert 参数只有一个包名。
- [ ] 运行目标测试并确认失败。
- [ ] 在 `/api/v1/log` 的事实 insert 成功前后保持同一 session 事务，并对 `body.package_name` 调用一次 `ensure_package_sources(..., has_log=True)`；不要在事件循环内按 `logs` 每条调用。若目录 upsert 失败，沿用现有 500 + rollback 行为。
- [ ] 在 `/api/v1/usage-duration` 的 `db.add/flush` 同一 session 中调用一次 `ensure_package_sources(..., has_usage=True)`；保留现有响应 envelope 和校验行为。
- [ ] 增加热路径证据测试：重复已有包请求的 SQL 只包含主键读取、不包含目录 UPDATE；缺来源请求只产生一次 INSERT/条件 UPDATE；并发同包、并发不同来源和目录异常回滚均有真实 PostgreSQL 测试，记录平均/分位耗时，不用 mock 作为性能结论。
- [ ] 运行 SDK API 集成测试并提交：`git add backend/app/api/sdk backend/tests && git commit -m "feat(api): maintain package catalog on ingest"`。

## 任务 4：切换管理端下拉并保持旧 API 契约

**文件：** `backend/app/services/log_export_service.py`、`backend/app/api/admin/log_exports.py`、`backend/tests/test_log_export_api.py`。

- [ ] 先写失败测试：mock/SQL capture 断言日志包名 API 查询 `PackageCatalog.has_log`，usage API 查询 `PackageCatalog.has_usage`，都不引用事实表；关键字、排序、limit 和 `{code:0,data:{items}}` 不变。
- [ ] 运行测试确认失败。
- [ ] 将两个服务函数改为：当 `PACKAGE_CATALOG_READS_ENABLED=false` 时保持旧查询；为 `true` 时只委托目录查询。API 层保留现有参数验证、管理员鉴权和响应结构。不要修改 actual events、统计、export 的事实查询；不得捕获目录查询错误后自动退回旧查询。
- [ ] 增加真实 PostgreSQL 查询计划测试/脚本：在 snapshot 数据上先运行旧查询与新查询对比结果，再对新查询执行 `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`，断言计划中没有 `sdk_events`/`sdk_usage_durations` relation；记录耗时和返回集合一致性。
- [ ] 运行定向测试并提交：`git add backend/app/services/log_export_service.py backend/app/api/admin/log_exports.py backend/tests/test_log_export_api.py scripts && git commit -m "fix(admin): search package names from catalog"`。

## 任务 5：实现可重跑、受控的历史补齐

**文件：** `scripts/backfill_package_catalog.py`、`scripts/test_backfill_package_catalog.py`、`docs/07-DEPLOYMENT.md`。

- [ ] 先写失败测试，覆盖：按 `(server_ts,id)` 游标、batch size、statement timeout、每批 commit、异常重跑不重复/不清标记、日志与 usage 两来源独立补齐、达到 EOF 后计数校验。
- [ ] 运行：`pytest -q scripts/test_backfill_package_catalog.py`；预期先失败。
- [ ] 实现两个来源的 SQL 游标批次：从事实表只取 `package_name, server_ts, id`，按 keyset 条件排序并限制批量；批次内 Python 去重后调用同一个目录 upsert SQL；`SET LOCAL statement_timeout` 保护每批；输出 JSON/文本进度包含 source、last cursor、rows、batches。脚本支持 `--database-url`、`--batch-size`、`--statement-timeout-ms`、`--resume-*`、`--max-batches`、`--apply`，默认 dry-run 或显式 `--apply`，不能把生产写入藏在默认路径。
- [ ] 说明连续写入策略：schema 完成后先补齐并部署新 writer，但目录读开关仍关闭；确认旧 writer 排空后，从头执行 final pass；final pass commit 后做事实表→目录、目录→事实表两方向差集，均为零后才启用目录读取。每个 pass 的 OR upsert 可安全重跑，checkpoint 仅在 commit 后推进；final pass 结束后新写由同事务 ensure 覆盖。
- [ ] 使用本地授权测试库和 snapshot 真实 PostgreSQL 验证约 54,025/47,596 行数据，记录批次数、耗时、最终日志/usage 包名数量与 API 结果；不接受只用 mock 的性能结论。脚本不得把 DSN、密码或 token 放入命令行参数或日志，优先使用环境变量/受保护 env 文件；不得连接生产库。
- [ ] 提交：`git add scripts/backfill_package_catalog.py scripts/test_backfill_package_catalog.py docs/07-DEPLOYMENT.md && git commit -m "feat(ops): add resumable package catalog backfill"`。

## 任务 6：全量验证、发布门槛与回滚材料

**文件：** `docs/03-DATABASE.md`、`docs/07-DEPLOYMENT.md`、必要的测试文件。

- [ ] 运行后端单元/API 测试：`cd backend; pytest -q tests/test_package_catalog_migration.py tests/test_package_catalog_service.py tests/test_log_export_api.py <SDK API tests>`。
- [ ] 运行真实 PostgreSQL 集成测试和 `EXPLAIN ANALYZE`；输出必须包含：事实表查询未被目录 API 触发、log/usage 来源集合分别正确、同事务回滚成立、重复补齐计数稳定、目录查询响应时间与旧基线对比。
- [ ] 运行现有后端全量测试及前端全量测试/构建；执行 `git diff --check`。
- [ ] 文档写明上线顺序：先 additive schema migration，再保持开关关闭部署新 writer，确认旧 writer 排空，执行从头 final backfill 和两方向差集校验，最后显式设置 `PACKAGE_CATALOG_READS_ENABLED=true`；任一步失败停止发布，不删除目录或事实数据。回滚应用时保留目录表，恢复旧读路径必须由 review 明确批准并通过配置变更完成，不得作为异常自动 fallback。
- [ ] 将每个独立提交 SHA、测试命令、真实 PG 结果和未执行的生产动作报告给 root/reviewer；本计划阶段不执行生产迁移或发布。

## 自检

- 规格覆盖：目录唯一性、双来源标记、历史补齐、新写增量、多实例/回滚可靠性、热路径成本、迁移兼容/回滚、API 语义、无事实表 fallback、真实 PG 验证均有对应任务。
- 失败窗口处理：目录读开关在旧 writer 排空和 final 从头补齐完成前保持旧路径；最终 pass 覆盖晚提交旧 writer 数据，所有新实例写入均与事实表同事务完成。
- 禁止行为：不使用进程缓存作为正确性来源；不引入 Redis/队列；不延长现有 API 超时来掩盖慢查询；不执行生产写入。
