# 生产日志快照预检记录

## 当前状态

本轮只完成准备和连接安全检查，未读取生产数据库、未导出数据、未写入生产、未执行 DDL、未暂停任务，也未触发长事务。

- 既有本地验收库 `sdk_local_acceptance_20261018` 保持不动；本次新建独立导入库 `sdk_prod_snapshot_20261018_001`。
- 目标北京时间日范围：`2026-10-18 00:00:00` 至当前快照时间；对应 UTC 半开区间：`2026-10-17T16:00:00Z <= ts < 2026-10-18T16:00:00Z`。
- 预检脚本：[scripts/prod_log_snapshot_preflight.sql](../../../scripts/prod_log_snapshot_preflight.sql)
- 生产连接：按 SDK 部署记录使用 `root@104.244.92.6`、`id_ed25519_hill_yu` 和严格 `known_hosts` 校验成功；未使用密码。此前 `349f8a6` 中误用的 `104.244.95.68` 属于其他部署记录，已纠正。

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

若连接失效，必须重新使用已确认的 SDK 部署目标、用户名和对应已授权 key（不发送私钥内容）；不得回退到其他项目主机或历史密码。

## 实际只读预检结果（2026-10-18）

- 快照上界：`2026-10-18T14:58:52Z`，即北京时间约 22:58；当天尚未结束。
- `sdk_events` 按 `server_ts` 分区；`2026-10` 分区估算 366,031 行、458 MB。目标日 planner 估算约 13,319 行，计划只触及 `sdk_events_202610`，但当前没有 `(server_ts, id)` 索引，选择了该分区 Seq Scan + 排序；不可无边界大扫。
- `sdk_usage_durations` 估算 289,570 行、135 MB；目标日 planner 估算约 42,148 行，使用 `idx_usage_durations_server_ts` Index Scan。
- 解析 Stage/正式表：H1 Stage 约 205,397 行/442 MB，Click Stage 约 390,032 行/92 MB，正式 H1 约 193,211 行/446 MB，正式 Click 约 381,132 行/106 MB；不能按正式表替代 Stage，也不能混用 `job_id`。
- `sdk_log_reparse_jobs` 仅约 20 行，目标日范围没有重叠任务（0 rows）；本次不导入解析 Stage，不声明有完整 history job。
- 预检期间连接均为 idle，无 active/waiting query；事务最终 `ROLLBACK`。

建议的后续读取方案（仍需 root 确认）：事件按 `server_ts` 日边界、稳定游标 `(server_ts,id)`、每批最多 500 行、单批 statement timeout 5 秒，批次间限速；使用时长按 `(server_ts,id)` 同样分批。由于事件目标日计划仍是分区 Seq Scan，先追加一个 planner-only keyset `EXPLAIN` 并评估单批成本，若单批超时则暂停，不建索引、不改变生产计划任务。

## 导出脚本安全修正记录

- root 已批准方案后，旧版脚本在审查阻断前实际完成了 2 个 events 批次，共 1000 行、约 855KB；未开始 usage，没有 manifest，未导入本地。该 `.local-run` 文件是失败证据，禁止作为导入输入，不提交到 Git。
- 随后已停止远端调用；生产复核显示只有 idle 连接、无 active 导出查询。
- 新版脚本提交 `2063a67`：远程只解析 DB 连接字段并用进程内 `PGPASSWORD`，每次短事务 READ ONLY；唯一 run 目录、partial 文件、完成 manifest、SHA-256、固定时间窗、行数/字节上限；本地导入强制 `127.0.0.1:55432/sdk_prod_snapshot_20261018_001`、要求空库和完整 manifest，并按 500 行本地事务批量导入。
- `scripts/test_snapshot_import.py`：4 passed；新 SHA 未经独立复审前不再次连接生产。
