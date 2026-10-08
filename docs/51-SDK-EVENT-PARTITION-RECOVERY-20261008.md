# SDK 原始事件分区缺口与生产恢复记录

日期：2026-10-08

本文只记录 2026-10-08 生产原始日志停止与恢复事件，不包含密码、Token、数据库 URL 或原始生产 payload。解析、设备时长、版本下拉和旧 8102 进程不在本次修复范围内。

## 根因证据

- 生产 `sdk_events` 是按 `server_ts` 的 PostgreSQL range partition，边界使用 UTC `timestamptz`。
- 故障发生时实际只有 `sdk_events_202607`、`sdk_events_202608`、`sdk_events_202609`；`sdk_events_202609` 的上界为 `2026-10-01 00:00:00+00`，不存在 `sdk_events_202610`。
- `max(server_ts)` 为 `2026-09-30 23:59:59.622786+00`，即北京时间 10 月 1 日 07:59:59；之后的上报无法匹配分区。
- `sdk-api` journal 的底层异常为 `asyncpg.exceptions.CheckViolationError: no partition of relation "sdk_events" found for row`，API 将其按既有逻辑包装为 500“数据库写入失败”。最早可见异常时间为 `2026-10-05 23:41:15`（北京时间），10 月 8 日仍重复出现。
- 缺分区期间被拒绝的上报没有落库，不能声称可以由分区恢复自动补回。

生产状态核对：PostgreSQL 16.14；父表 owner 为 `sdk_admin`；数据库角色具备创建分区所需的 schema/table 权限；磁盘、inode、内存、连接池和四个现行服务均正常。未重启 API、未迁移表结构、未删除或清理旧数据。

## 备份与恢复前快照

- 备份目录：`/root/sdk-deploy-backups/20261008_015315_sdk-event-partitions`
- PostgreSQL custom dump：`104730085` bytes；`pg_restore -l`：`166` entries。
- 快照文件：`schema_snapshot_before.json`，保存真实父表 OID、server_ts 分区键、父表及旧分区 owner/ACL、分区 bounds、索引和计数。
- 恢复前旧分区计数：`sdk_events_202607=2`、`sdk_events_202608=867`、`sdk_events_202609=205365`。

## 最小恢复 DDL

只创建缺失的当前月及未来两个月分区，使用显式 UTC 连续边界：

```sql
CREATE TABLE IF NOT EXISTS public."sdk_events_202610"
PARTITION OF public."sdk_events"
FOR VALUES FROM ('2026-10-01 00:00:00+00') TO ('2026-11-01 00:00:00+00');

CREATE TABLE IF NOT EXISTS public."sdk_events_202611"
PARTITION OF public."sdk_events"
FOR VALUES FROM ('2026-11-01 00:00:00+00') TO ('2026-12-01 00:00:00+00');

CREATE TABLE IF NOT EXISTS public."sdk_events_202612"
PARTITION OF public."sdk_events"
FOR VALUES FROM ('2026-12-01 00:00:00+00') TO ('2027-01-01 00:00:00+00');
```

执行在单个短事务内完成，设置 `lock_timeout=3s`、`statement_timeout=10s`，并使用 `pg_try_advisory_xact_lock` 互斥；失败路径回滚并返回非零。恢复前后不调用既有 `create_next_partition()` 或 `cleanup_old_partitions()`，不执行 `init_db.sql`。

## 预检与执行结果

前置适配预检曾三次按 fail-closed 停止，均发生在任何 `CREATE` 前：asyncpg catalog 值为 `bytes`、bounds 文本包含 `FOR VALUES` 前缀，修正为统一 UTF-8 文本归一化和完整 bounds 解析后，纯只读校验确认 `server_encoding=UTF8`、父表为 range partition、单列 `server_ts timestamptz`、目标 202610/11/12 全部缺失且无重叠。

最终事务提交成功：

- `sdk_events_202610` bounds 为 `[2026-10-01T00:00:00Z, 2026-11-01T00:00:00Z)`，owner `sdk_admin`。
- `sdk_events_202611` bounds 为 `[2026-11-01T00:00:00Z, 2026-12-01T00:00:00Z)`，owner `sdk_admin`。
- `sdk_events_202612` bounds 为 `[2026-12-01T00:00:00Z, 2027-01-01T00:00:00Z)`，owner `sdk_admin`。
- 每个新分区均验证到 7 个有效的 parent→child 附属索引；父表和旧分区数据未删除。
- 未重启四个 API/worker 服务，未切换业务 release。

独立验收窗口随后确认自然 SDK 上报返回 200，旧分区计数未减少；本记录不把该结果扩展为解析、导出、设备时长或性能门禁全部通过。

## 后续维护实现状态

已在独立分支准备：

- `scripts/ensure_sdk_event_partitions.py`：默认 dry-run；apply 需要显式确认串；使用显式 UTC session、父表 OID、range/server_ts 类型、owner/ACL 基线、parent→child index/`indisvalid`、短超时和 advisory 互斥；禁止 `--apply --as-of`；成功输出 `created`、`verified=true`、`committed=true`，失败输出脱敏摘要并返回非零。
- `deploy/systemd/sdk-event-partition-maintenance.service` 与 `.timer`：脚本放在独立 `/opt/sdk-platform-maintenance/<commit>/scripts/`，复用当前 release 的 `.env`/venv，不切换业务 API release。
- 本地 PostgreSQL 集成测试仅允许 loopback 且数据库名为唯一 `sdk_partition_test_<suffix>`，覆盖真实 dry-run 无 DDL、旧 fixture 计数保留、apply、幂等 apply、advisory 冲突快速拒绝和 DDL 后置校验失败 rollback；专项 9 项通过，后端全量 `412 passed, 1 skipped`。

## 独立维护 timer 安装与验收

经独立代码审查放行后，维护版本按原子切换流程安装；本次安装不切换业务 release，也未重启 API/worker：

- 维护提交：`44856caa1df0d0bd2165102080ae161d193c4dbc`；生产 `ensure_sdk_event_partitions.py` SHA-256 为 `00b8909c1bda2358f83e0d8feb3a23a02d65f65dc1177d5a2faf74bc83312bb0`，与本地版本一致。
- 安装目录：`/opt/sdk-platform-maintenance/44856caa1df0d0bd2165102080ae161d193c4dbc`，`/opt/sdk-platform-maintenance/current` 原子指向该目录；脚本为 `root:root 0755`，两个 unit 为 `root:root 0644`。
- 安装前备份：`/root/sdk-deploy-backups/20261008_021738_partition-maintenance-install`，保存旧 `current` 指针及同名 unit 的状态（此前均不存在）。
- `systemd-analyze verify` 通过；以 `www-data` 最小环境执行 dry-run 返回 `current_month=2026-10-01`、目标 10/11/12 月、`missing=none`、`created=none`。一次继承 root `PGSSLKEY` 的包装器检查因无法读取 root 私钥失败，但未连接数据库或写入；未修改业务 `.env`、TLS 配置或权限，随后最小环境和真实 systemd 执行均成功。
- 真实 oneshot 首次执行成功：`missing=none`、`created=none`、`verified=true`、`committed=true`，service `Result=success`、`ExecMainStatus=0`；幂等执行未重复创建分区。
- timer 已 `enabled/active/waiting`，下一次触发为 `2026-10-09 00:18:56 UTC`，即北京时间 `2026-10-09 08:18:56`（含随机错峰延迟）。
- 独立真实 PostgreSQL 集成证据：`1 passed, 9 deselected`；生产只读复核确认旧分区计数 `2/867/205365` 未减少，10 月分区持续有新数据，20 分钟窗口内上报连续 `HTTP 200` 且未出现新的 `no partition`。
- 业务 API release 仍为 `a822891065c7439cfa27cf70c11f26e6ea9cdf71`；四个业务进程 PID 未变，均保持 active、`NRestarts=0`、`ExecMainStatus=0`。维护版本 `44856ca...` 仅由独立 service 使用。

旧 `create_next_partition()` 仅保留为 legacy，不用于修复已存在的分区缺口。
