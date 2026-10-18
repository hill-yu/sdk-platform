# 生产日志快照预检记录

## 当前状态

本轮只完成准备和连接安全检查，未读取生产数据库、未导出数据、未写入生产、未执行 DDL、未暂停任务，也未触发长事务。

- 目标本地导入库：独立的 `sdk_local_acceptance_20261018`，不覆盖既有本地库。
- 目标北京时间日范围：`2026-10-18 00:00:00` 至当前快照时间；对应 UTC 半开区间：`2026-10-17T16:00:00Z <= ts < 2026-10-18T16:00:00Z`。
- 预检脚本：[scripts/prod_log_snapshot_preflight.sql](../../../scripts/prod_log_snapshot_preflight.sql)
- 生产连接结果：SSH 只读握手未通过，目标拒绝现有本地 key；因此没有猜测主机、用户名或凭据，也没有继续尝试数据库连接。

## 预检设计

脚本只使用单连接事务，设置 `READ ONLY`、15 秒 statement timeout、2 秒 lock timeout 和 30 秒 idle-in-transaction timeout。输出内容包括：

- 目标事实表/Stage/配置维表的 schema、estimated rows、relation size；
- 时间列、主键、索引、`sdk_events` 分区边界；
- 当前连接/等待状态；
- `sdk_events.server_ts`、`sdk_usage_durations.server_ts` 和解析任务范围查询的 `EXPLAIN (FORMAT JSON)`，不使用 `ANALYZE`，不做全表 `COUNT(*)`。

## 导入边界（待生产连接复核后执行）

- 原始事件使用 `sdk_events.server_ts`，按稳定游标 `(server_ts, id)` 小批 keyset 读取；不要用 `client_ts` 替代。
- 使用时长使用 `sdk_usage_durations.server_ts`，按 `(server_ts, id)` 读取。
- 解析历史必须先发现完整且成功的 `sdk_log_reparse_jobs`；按 `job_id` 导出完整 Stage 上下文，不能只按日期截断 Stage 后宣称 job 完整。
- H1 正式表/Click 正式表没有 `job_id`，不能与 Stage 混用；关联键保留 `event_id + event_server_ts + record_index`，Click 额外保留 `attempt_index`。
- 配置仅导入本地测试所需的非敏感版本/包维表；不导入生产 COS/CDN 密钥、token 或外发地址作为可执行配置，不启动生产 worker，不执行发布。

## 待补信息

需要从已确认的部署记录提供本项目生产数据库的 SSH 目标/用户名和对应已授权 key（不发送私钥内容）。拿到后先只运行预检脚本，回报实际 schema、索引可用性、planner 估算行/大小、当前负载与低影响分批方案，等待确认后才开始导出。
