# SDK 原始事件分区维护实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 补齐 `sdk_events` 当前月份及未来两个月的缺失分区，并提供可安全重复执行的每日维护任务，避免跨月后 SDK 日志上报因无匹配分区返回 500。

**架构：** 新增独立 Python 维护脚本，不调用既有 `create_next_partition()`、`cleanup_old_partitions()` 或 `init_db.sql`。脚本以数据库 UTC 月初为边界，先锁定真实父表、校验 catalog bounds/同名与异名重叠，再在短事务中只创建缺失分区；失败时整个事务回滚并返回非零。systemd service 使用现有 release 的 `.env`/venv，但脚本安装在独立的版本化维护目录 `/opt/sdk-platform-maintenance/<commit>/scripts/`，通过 `/opt/sdk-platform-maintenance/current` 指向当前维护版本，不切换业务 API release。

**技术栈：** Python 3.12、SQLAlchemy async、asyncpg、PostgreSQL declarative range partition、systemd service/timer、pytest。

---

## 文件职责

- 创建：`scripts/ensure_sdk_event_partitions.py`——dry-run/apply、UTC 月份计算、catalog 校验、短事务 DDL、结果输出。
- 创建：`deploy/systemd/sdk-event-partition-maintenance.service`——使用当前 release 的 venv 与 `.env`，执行独立 `/opt/sdk-platform-maintenance/current/scripts/` 中的维护脚本。
- 创建：`deploy/systemd/sdk-event-partition-maintenance.timer`——每日触发 service，保留 `Persistent=true`。
- 创建：`backend/tests/test_sdk_event_partition_maintenance.py`——跨年/月边界、缺失分区、同名错误、异名重叠、幂等和 unit 契约测试。
- 更新：`docs/50-LOG-METRICS-DEVICE-DURATION-H1-EXPORT-IMPLEMENTATION-20260930.md`——仅在生产恢复与最终审阅证据完成后记录本故障和运维事实，不提前标记全部验收通过。

## 任务 1：先写失败测试，锁定安全边界

**文件：** `backend/tests/test_sdk_event_partition_maintenance.py`

- [ ] **步骤 1：编写测试**

  测试直接调用脚本的纯函数和 fake catalog 适配层，覆盖：

  ```python
  def test_target_months_cross_year_boundary():
      assert target_months(date(2026, 12, 15)) == [
          date(2026, 12, 1), date(2027, 1, 1), date(2027, 2, 1)
      ]

  def test_missing_partition_plan_contains_only_missing_exact_months():
      existing = {"sdk_events_202610": (date(2026, 10, 1), date(2026, 11, 1))}
      assert build_plan(date(2026, 10, 8), existing) == [
          ("sdk_events_202611", date(2026, 11, 1), date(2026, 12, 1)),
          ("sdk_events_202612", date(2026, 12, 1), date(2027, 1, 1)),
      ]

  def test_same_name_with_wrong_bounds_fails_closed():
      with pytest.raises(PartitionSafetyError):
          build_plan(date(2026, 10, 8), {
              "sdk_events_202610": (date(2026, 10, 2), date(2026, 11, 2))
          })

  def test_alias_partition_overlapping_target_fails_closed():
      with pytest.raises(PartitionSafetyError):
          build_plan(date(2026, 10, 8), {
              "sdk_events_legacy_oct": (date(2026, 10, 1), date(2026, 11, 1))
          })

  def test_idempotent_plan_is_empty_when_all_three_exact_bounds_exist():
      existing = {
          "sdk_events_202610": (date(2026, 10, 1), date(2026, 11, 1)),
          "sdk_events_202611": (date(2026, 11, 1), date(2026, 12, 1)),
          "sdk_events_202612": (date(2026, 12, 1), date(2027, 1, 1)),
      }
      assert build_plan(date(2026, 10, 8), existing) == []
  ```

- [ ] **步骤 2：运行测试确认红灯**

  运行：`pytest -q backend/tests/test_sdk_event_partition_maintenance.py`

  预期：因 `scripts.ensure_sdk_event_partitions` 尚未存在而失败；失败原因必须是导入/符号缺失，而不是测试语法错误。

## 任务 2：实现最小安全维护脚本

**文件：** `scripts/ensure_sdk_event_partitions.py`

- [ ] **步骤 1：实现纯函数与 catalog 规划**

  使用 `date` 计算 `[current_month, current_month+1, current_month+2]`，月份加法独立处理 12 月进位。catalog 查询必须返回真实父表 `public.sdk_events` 的 OID、每个直接子分区名称、`pg_get_expr(relpartbound, oid)` 解析后的 UTC 起止边界及拥有者。父表不存在、父表不是 range partition、子分区 bounds 无法解析、同名 bounds 不精确匹配、任意异名分区与目标月重叠时抛出 `PartitionSafetyError`。

- [ ] **步骤 2：实现 dry-run/apply 事务**

  使用 `create_async_engine()` 和现有 `DATABASE_URL`/`get_settings().resolved_database_url`，apply 前在同一连接执行：

  ```sql
  SET TRANSACTION ISOLATION LEVEL READ COMMITTED;
  SET LOCAL lock_timeout = '3s';
  SET LOCAL statement_timeout = '10s';
  SELECT pg_try_advisory_xact_lock(hashtextextended('sdk_events_partition_maintenance', 0));
  ```

  未取得 advisory lock 直接返回非零且不等待；DDL 只使用内部生成并经严格校验的分区名和显式 `+00:00` bounds，逐个 `CREATE TABLE ... PARTITION OF`。任何异常都让事务 rollback；成功后重新读取 catalog，验证三个月目标均存在、bounds 精确连续、owner/ACL 可读且每个新分区具备父表附属索引。

- [ ] **步骤 3：实现 CLI 契约**

  默认 `--dry-run`，`--apply` 必须同时传 `--confirm ENSURE_SDK_EVENT_PARTITIONS`；输出当前 UTC 月份、目标三个月、缺失列表、创建列表和验证结果，不输出数据库 URL、密码或 Token。脚本禁止执行 `DROP`、`DELETE`、`TRUNCATE`、`cleanup_old_partitions()` 和既有维护函数。

- [ ] **步骤 4：运行测试确认绿灯**

  运行：`pytest -q backend/tests/test_sdk_event_partition_maintenance.py`

  预期：新增测试全部通过。

## 任务 3：加入每日 systemd 维护任务

**文件：** `deploy/systemd/sdk-event-partition-maintenance.service`、`deploy/systemd/sdk-event-partition-maintenance.timer`、测试文件。

- [ ] **步骤 1：编写 service/timer 契约测试**

  断言 service 使用 `User=www-data`、`EnvironmentFile=/www/releases/sdk-platform/current/backend/.env`、current release 的 venv/script、`--apply --confirm ENSURE_SDK_EVENT_PARTITIONS`，timer 包含 `OnCalendar`、`Persistent=true` 和正确 service 名称；断言 unit 不含密码、Token、旧 `/www/wwwroot` 占位路径。

- [ ] **步骤 2：写 unit 文件并运行专项测试**

  service 不重启 API，不依赖 API；`PYTHONPATH` 仅指向当前 release 的 backend 以复用现有 settings，脚本本身从独立维护目录加载；timer 每日 UTC 触发，`RandomizedDelaySec` 仅用于错峰。运行：`pytest -q backend/tests/test_sdk_event_partition_maintenance.py`。

## 任务 4：验证、提交与生产恢复交接

- [ ] **步骤 1：本地验证**

  运行 `pytest -q backend/tests/test_sdk_event_partition_maintenance.py`、`git diff --check`，必要时使用临时 PostgreSQL 执行 dry-run/apply 两次，第二次必须报告无缺失且不产生新 DDL。若无法启动临时 PostgreSQL，保留纯函数和 fake catalog 证据，不伪称真实数据库测试通过。

- [ ] **步骤 2：生产写入前检查**

  由 root 接收有效 `pg_dump --format=custom` stdout 并校验大小/`pg_restore -l`；在 `statement_timeout` 下保存父表 schema、202607/202608/202609 分区 bounds 与逐分区历史计数；检查目标缺口、父表 owner/ACL、连接池和当前业务锁；不执行 API 重启。

- [ ] **步骤 3：最小生产恢复**

  在短事务、advisory 互斥和 lock/statement timeout 保护下只创建缺失的 `sdk_events_202610`、`sdk_events_202611`、`sdk_events_202612`，立即重新读取 bounds/owner/ACL/附属索引并保存结果；失败必须非零并确认旧分区计数未变。

- [ ] **步骤 4：恢复后只读验证**

  先确认自然 SDK 上报成功并观察最新 `server_ts` 增长；如必须使用受控上报，只允许唯一精确事件并在得到单独授权后清理该事件，不能清理旧数据。确认不修改版本下拉、解析、时长和旧 8102 进程。

- [ ] **步骤 5：提交**

只提交维护脚本、unit、测试和计划；`docs/50` 等用户已有脏文件单独保留，生产证据待审阅结论后再记录。

## 任务 5：独立维护 timer 安装收口

- [x] **步骤 1：安装版本化维护文件并保留恢复指针**

  已安装提交 `44856caa1df0d0bd2165102080ae161d193c4dbc` 到 `/opt/sdk-platform-maintenance/<commit>/`，并以 `current.new` + `mv -Tf` 原子切换 `current`。安装备份为 `/root/sdk-deploy-backups/20261008_021738_partition-maintenance-install`；未切换 `/www/releases/sdk-platform/current`。

- [x] **步骤 2：验证权限、unit 和实际执行**

  `systemd-analyze verify` 通过；`www-data` 最小环境 dry-run 报告 `missing=none`、`created=none`；真实 oneshot 报告 `verified=true`、`committed=true`，无新增 DDL。一次继承 root `PGSSLKEY` 的包装器检查仅因私钥权限失败，未连接数据库或写入，且未改动业务 TLS/环境配置。

- [x] **步骤 3：启用 timer 并记录独立验收证据**

  timer 已 `enabled/active/waiting`，下一次触发为 `2026-10-09 00:18:56 UTC`（北京时间 `2026-10-09 08:18:56`）。真实 PostgreSQL 集成测试为 `1 passed, 9 deselected`；业务 release 保持 `a822891065c7439cfa27cf70c11f26e6ea9cdf71`，维护提交保持 `44856caa1df0d0bd2165102080ae161d193c4dbc`，四个业务进程未重启。旧分区计数未减少，10 月上报持续返回 200。

- [x] **步骤 4：文档提交边界**

  本次仅提交 `docs/51` 和本计划文件；`docs/50-LOG-METRICS-DEVICE-DURATION-H1-EXPORT-IMPLEMENTATION-20260930.md` 的用户既有 dirty 改动不纳入提交。本次不合并、不推送。
