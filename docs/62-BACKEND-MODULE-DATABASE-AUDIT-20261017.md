# 后台模块与数据库业务审计

日期：2026-10-17
基线：`2ea1e0cd62f04db6b794a7d93464cf47c09742ce`
范围：`backend/app`、`backend/workers`、`scripts/init_db.sql`、分区维护脚本及既有部署/验收文档。本文是代码与文档静态审计，不连接生产、不运行生产长查询、不修改业务 SQL。

## 1. 结论边界与证据等级

| 等级 | 含义 |
| --- | --- |
| 已证实 | 代码、DDL 或既有记录可直接定位；不等于在当前审计中重新压测。 |
| 静态风险 | 从 SQL 形状、索引、事务边界或数据增长路径推断出的风险，需要在独立副本/代表性数据上 EXPLAIN 或压测。 |
| 未实测 | 当前 worktree 没有安全的生产执行证据，本文不把“能运行”写成“不卡顿”。 |

主会话已有真实观察日志报告过 2026-10-12 的 metrics overview 超时；这属于“历史证据/已观察”，不是本次复现。当前基线可读取的 `docs/` 中没有该日志的逐行原始记录，因此本文不把它冒充为本次实测。可复核的另一条历史记录是 `docs/55-PARSE-STAGE-BIND-LIMIT-PRODUCTION-DEPLOYMENT-20261009.md:72-75` 的 215 条既有 H1 超时，但那是解析阶段，不是 overview SQL。

## 2. 运行时、连接与后台任务

| 项目 | 现状与证据 | 审计判断 |
| --- | --- | --- |
| 连接池 | `backend/app/core/database.py:12-20`：每进程 `pool_size=20`、`max_overflow=10`、`pool_timeout=5`、`pool_pre_ping`、`pool_recycle=1800`。 | 静态风险：多 admin worker 会按进程复制 20+10；长查询或发布网络等待会占用连接。 |
| 提交边界 | `database.py:23-52` 的 `get_db()` 在依赖结束时 commit/rollback/close；`get_db_no_commit()` 只读不提交。 | 已证实：路由通常以请求为事务边界；服务内部显式 commit 的 worker 另列。 |
| ETL | `backend/app/admin_main.py:21-43` 启动立即执行 `SELECT refresh_materialized_views()`，之后每 300 秒执行；`:70-103` 作为 lifespan task 启动。 | 静态风险：每个 admin 进程各起一条刷新循环；`REFRESH MATERIALIZED VIEW CONCURRENTLY` 仍可能消耗大量 IO/CPU。函数用 advisory xact lock 防止同一数据库重叠。 |
| 导出 worker | `backend/app/workers/log_export_worker.py` 先短事务 claim pending job，再按批次读取/写 CSV，结果另开事务更新。 | 已证实：不把整个导出文件过程放在单个 DB 事务；静态风险是大范围筛选、磁盘、网络下载。 |
| 解析 worker | `backend/app/workers/log_parse_worker.py` claim 后逐批处理、提交 stage/final 结果，decoder 使用受限 ProcessPoolExecutor 和 per-event timeout。 | 已证实：批次事务较短；静态风险是 CPU/进程池、stage 表写放大和历史任务规模。 |
| 分区维护 | `scripts/ensure_sdk_event_partitions.py` 默认 dry-run；apply 使用 UTC、`lock_timeout=3s`、`statement_timeout=10s`、advisory lock、单事务，并校验父表/边界/owner/ACL/index。 | 已证实安全护栏；未实测生产执行结果。 |

## 3. 数据表、分区、物化视图与索引

以下来自 `scripts/init_db.sql`，行号以本基线为准。

| 表/对象 | 关键结构 | 主要索引/约束 | 业务含义与风险 |
| --- | --- | --- | --- |
| `sdk_events` (`init_db.sql:15-63`) | `RANGE(server_ts)`；复合主键 `(id,server_ts)`。 | `event_type,server_ts`；`device_id,server_ts`；`package_name,server_ts`；`session_id,server_ts`；payload GIN；`client_ts`。 | SDK click/log/error 主事实表；日期条件可分区裁剪，未带日期的 count/distinct、filter options 会扫很多分区。 |
| `sdk_usage_durations` (`:66-88`) | duration check 1..3600。 | `server_ts`；`package_name,server_ts`；`package_name,device_id,server_ts`。 | 使用时长事实；latest-per-device 的排序前缀较匹配，31 天窗口仍可能较大。 |
| `sdk_configs` (`:92-120`) | `(package_name,version)` unique；published 状态约束。 | `(package_name,status,created_at DESC)`；published partial unique `(package_name)`。 | 配置历史与当前发布态；全量历史列表无分页是增长风险。 |
| `sdk_versions` (`:122-147`) | `(platform,version_code)` unique。 | `(platform,version_code DESC)`。 | 版本管理与 SDK latest 查询；索引匹配良好。 |
| `sdk_log_decodes` (`:150-182`) | 复合主键 `(event_id,event_server_ts,record_index)`。 | package/time、status/time、decoder_status、event/time。 | log 解析结果；summary/details 以 event_id+server_ts join，若一事件多 record，join 行数会放大。 |
| `sdk_package_profiles`、`sdk_admin_preferences` (`:184-201`) | package/preference 主键。 | updated_at 辅助索引。 | 别名、公司、账号及日志列配置；读写均为小范围 PK/upsert。 |
| `sdk_log_reparse_jobs` (`:203-239`) | status、日期范围、lease 字段。 | `(status,created_at)`、range 索引。 | 解析任务队列；claim 的 `FOR UPDATE SKIP LOCKED` 与状态索引匹配。 |
| H1/click 正式结果 (`:241-280`) | 复合事件键；click 另含 attempt_index。 | H1 `(package_name,event_server_ts,config_id)`；click `(package_name,event_server_ts,config_id,target_kind)`。 | metrics 的 package/time/config/target 过滤有前缀支持；status/failure/category 不是前缀。 |
| H1/click stage (`:282-332`) | 复合 job/event 键。 | job_id 索引。 | 批量解析暂存；绑定参数和清理规模是容量重点。 |
| `sdk_log_export_jobs` (`:342-371`) | UUID、status、mode/hour checks。 | `(status,created_at)`。 | 导出队列；文件生命周期不由 DB 表单独解决。 |
| `mv_daily_event_stats`、`mv_hourly_trend` (`:374-416`) | 按日/小时聚合。 | 各自 unique index。 | trend 查询读 MV；刷新成本与源表增长相关。 |
| 分区函数 (`:417` 起) | `create_next_partition()`、`cleanup_old_partitions(retention_days=90)`。 | 以 server_ts bounds 管理。 | 90 天留存是代码约定；必须核对实际 scheduler/执行记录，本文不宣称生产已执行。 |

## 4. SDK 写入与读取接口

| Endpoint | DB/事务 | 筛选/索引 | 风险与结论 |
| --- | --- | --- | --- |
| `GET /health` (`backend/app/sdk_main.py:20`) | 无 DB。 | 无。 | 健康检查不代表 admin 登录或受保护 API 可用。 |
| `POST /api/v1/click` (`backend/app/api/sdk/click.py:23-`) | 批量 insert `sdk_events`；`get_db()` 请求结束提交。 | 写入依赖 server_ts 分区；payload JSONB。 | 已有 SDK write limiter；无本次新增 idempotency。 |
| `POST /api/v1/log` (`backend/app/api/sdk/log.py:22-`) | 批量 insert `sdk_events`；返回事件 id。 | 同上。 | 重试去重/大批量 payload 仍需业务侧控制；不与 admin 登录限流复用。 |
| `POST /api/v1/usage-duration` (`backend/app/api/sdk/usage_duration.py:19-`) | 单条 usage insert；自动 commit。 | server_ts、package/device 前缀索引。 | 既有文档已说明重试可能重复；本文不改业务语义。 |
| `POST /api/v1/config/meta` (`backend/app/api/sdk/config.py:25-`) | 读 `sdk_configs`，按 package/status/COS 状态取元信息；解密在进程内。 | package/status partial/composite index 较匹配。 | 加密 CPU 与 COS 状态依赖；未实测 P99。 |
| `POST /api/v1/config/packages/{package_name}/versions/{version}/{config_type}` (`config.py:47-`) | 读发布配置、解密/封装。 | package/version/status。 | 不写 DB；配置密文不进入 admin session。 |
| `GET /api/v1/version` (`version.py:14-`) | 读 `sdk_versions` latest active。 | platform/version_code DESC 直接匹配。 | 低风险；未实测在大历史量下的响应时间。 |

## 5. Dashboard 与配置/版本后台接口

| Endpoint | service/query | 读写、事务、分页 | 索引与风险 |
| --- | --- | --- | --- |
| `GET /api/admin/dashboard/summary` (`dashboard.py:18`) | `analysis_service.get_summary` (`analysis_service.py:20-31`) 对整张 `sdk_events` 做多个 `COUNT FILTER`，时间条件只在 FILTER 内，没有外层 WHERE。 | 只读；单请求聚合。 | 已证实 SQL 形状风险：没有外层日期谓词，不能依靠该语句做分区裁剪，存在全历史分区扫描 + count/distinct 聚合风险；需代表性数据 EXPLAIN。 |
| `GET /dashboard/trend` (`dashboard.py:23`) | `get_trend` 读 `mv_hourly_trend` 或 `mv_daily_event_stats`。 | 只读；24h/7d/30d。 | MV unique index 匹配时间/类型；刷新与查询资源竞争是静态风险。 |
| `GET /dashboard/breakdown` (`:32`) | `sdk_events` 按日、event type、payload page/element group/order。 | 只读；带日期条件。 | 可分区裁剪；JSONB 提取、group/order CPU 风险。 |
| `GET /events` (`:42`) | 动态 event/package/sdk/device/date/hour/payload level filter；先 count，再 order `server_ts DESC` + `LIMIT/OFFSET`。 | 只读；page size <=100。 | package/time 索引较好；sdk_version/log_level JSON 过滤不完全匹配；深页 OFFSET 风险；count 与 page 双扫描。 |
| `GET /events/filter-options` (`:84`) | 两个 `DISTINCT ... ORDER BY` 查询取 `SdkEvent.package_name` / `SdkEvent.sdk_version` 专列。 | 只读；默认无日期。 | 静态风险：全量 log 事件 distinct，可能扫大量分区；sdk_version 不是 JSON payload 提取。 |
| `GET /configs` (`config_mgr.py:24`) | `config_service.list_configs` 查询 `SdkConfig`，created_at/id 倒序，Python 分 status。 | 只读；无分页。 | 单 package 可用 package 索引；全历史配置量增长风险。 |
| `GET /configs/reconcile` (`:33`) | 读配置与 COS 状态并 reconcile。 | 只读但有外部网络调用。 | 外部 COS 延迟；须避免在 DB 事务内长时间持有锁。 |
| `GET /configs/{id}` (`:84`) | PK 读并解密密文。 | 只读；进程 CPU。 | PK 良好；解密耗时未实测。 |
| `POST /configs` (`:92`) | validate roots、加密 JSON、insert/flush，依赖结束 commit。 | 写；短 DB 事务。 | 密码/配置 token 不应进日志；加密 CPU 未实测。 |
| `PUT /configs/{id}` (`:97`) | `get_db_no_commit`，读 draft、加密、flush，路由显式 commit。 | 写；请求内事务。 | 无乐观锁；并发编辑覆盖风险，当前计划不改业务。 |
| `POST /configs/{id}/publish` (`:132`) | package advisory xact lock；解密/校验、COS 上传重试、archive 旧 published、发布当前。 | 写；网络调用发生在持有 DB 事务/锁期间。 | 已证实设计；高静态风险：COS 慢会占连接和事务锁，partial unique 保证单 published；发布锁与连接池容量需压测。 |
| `POST /configs/{id}/rollback` (`:145`) | 与 publish 类似，读取来源、上传、archive 当前、发布来源。 | 写；同样持有 advisory lock。 | 同上；不在本次登录实现中改 SQL。 |
| `GET /versions` (`version_mgr.py:15`) | `version_service.list_versions`，platform asc/version desc。 | 只读；无分页。 | platform/version 索引匹配；版本历史增长仍应关注响应大小。 |
| `POST /versions`、`PUT /versions/{id}` (`:23-28`) | insert/update/flush，外层自动 commit。 | 写；短事务。 | unique platform/version 约束；并发冲突依赖 DB 错误处理。 |

## 6. 日志分析、metrics、usage 与导出

| Endpoint | 查询形状/表 | 事务和分页 | 审计风险 |
| --- | --- | --- | --- |
| `GET /api/admin/package-profiles`、`PUT /api/admin/package-profiles/{package}` (`log_analysis.py:35-75`) | package PK 读；PG upsert。 | 写路由提交。 | 低风险；配置错误会影响展示别名，不影响事实表。 |
| `GET/PUT /log-analysis/columns` (`:77-103`) | `sdk_admin_preferences` PK 读/upsert。 | 写路由提交。 | 低风险；不应把列配置当作权限。 |
| `GET /log-analysis/summary` (`:105-141`) | `sdk_events` log + `sdk_log_decodes` join；按 business date/package/profile 分组；先 count 再 page。 | `LIMIT/OFFSET`；只读。 | package/time 前缀部分匹配；join 未含 record_index，可能多 record 放大；JSON log level、group/count、深 OFFSET 风险。 |
| `GET /log-analysis/details` (`:143-179`) | decode 与 event 复合键 join，按 status/package/device/date/page。 | count + order + OFFSET。 | event_ts/package_ts 索引可用但组合不覆盖所有过滤；深 OFFSET 与 join 放大风险。 |
| `GET /log-analysis/details/{event_id}` (`:181-201`) | decode 复合 PK + event `(id,server_ts)`。 | 单条读。 | PK 对齐；若只给 event_id，仍需 server_ts/业务定位逻辑。 |
| `POST /log-analysis/reparse` (`:203`) | 当前入口立即返回 410；下方旧实现不可达。 | 无当前写入。 | 已证实：不要把旧代码当作当前 API 能力。 |
| `POST /api/admin/log-analysis/parse-jobs` (`log_metrics.py:92-119`) | 创建 `sdk_log_reparse_jobs` 记录并提交；由 worker 后续 claim。 | 写；请求短事务。 | 任务日期/范围与最大天数约束；不等于已执行解析。 |
| `GET /api/admin/log-analysis/parse-jobs/latest` (`:121-133`) | 读最新任务状态。 | 只读。 | 任务表 status/created 索引应匹配。 |
| `GET /api/admin/log-analysis/parse-jobs/{job_id}` (`:134-144`) | 读单任务及计数/错误摘要。 | 只读。 | 需结合 stage/final 规模核对序列化成本。 |
| `POST /api/admin/log-analysis/parse-jobs/{job_id}/cancel` (`:145-161`) | 更新任务取消状态并提交。 | 写；短事务；worker 后续识别状态。 | 与 worker claim/lease 并发语义需独立压测。 |
| `GET /log-analysis/coverage` (`:162`) | coverage 查询，按任务/范围统计。 | 只读。 | 需以 query plan 核对范围裁剪；当前未生产实测。 |
| `GET /api/admin/log-analysis/metrics/overview` (`:168`) | H1/click 多 scalar subquery + attempt_counts 外连接，再单独 target group。 | 只读，通常多次聚合扫描。 | 高静态风险：多个 scalar 子查询重复扫描；package/time 前缀索引部分匹配，但 status/failure/category 不在前缀；需独立副本压测。 |
| `GET /api/admin/log-analysis/metrics/configs` (`:176`) | H1/click 按 config_id count/group。 | 只读。 | package/time 前缀有帮助；全范围/大日期窗口可能聚合重。 |
| `GET /api/admin/log-analysis/metrics/targets` (`:184`) | click 按 target_kind group。 | 只读。 | target_kind 在索引后缀，必须结合 package/time 前缀才有选择性。 |
| `GET /api/admin/log-analysis/metrics/failures` (`:192`) | 非 success、可选 target/config，count + group/order。 | 只读。 | status/category 过滤非最佳前缀，静态风险同上。 |
| `GET /api/admin/log-analysis/metrics/h1` (`:209`) | H1 count/page，随后按当前页复合键取 click。 | page 用 OFFSET；二次 click 只查页内 keys。 | 页内二次查询控制了 join 范围；深页 OFFSET 仍有风险。 |
| `GET /usage-durations` (`usage_duration.py:35`) | legacy summary/list，sum/count/distinct 与分页。 | 只读；OFFSET。 | 汇总和列表双查询；旧端点需保留兼容但不应作为大数据分析入口。 |
| `GET /usage-durations/summary` (`:65`) | 最长 31 天；`row_number() over (package,device order by server_ts desc,id desc)` 取 latest，再 bucket CASE、count/order/page。 | count/group + OFFSET。 | 已实现七桶；package/device/time 索引前缀较匹配，但 window + 31 天规模风险。 |
| `GET /usage-durations/devices` (`:95`) | 同 latest-per-device，device_model 在 window 后过滤。 | 代码现状语义是“每设备最新记录后按机型筛选”，不是先按机型取 latest；有 count/page。 | 这是当前实现兼容语义，待业务确认；后置 model filter 可能先处理整个 package 设备集。 |
| `GET /log-packages` (`log_exports.py:17`) | log package distinct + 可选 `ILIKE '%keyword%'`。 | 只读、limit。 | 前导 wildcard 通常不能用普通 package btree 前缀，静态扫描风险。 |
| `POST /log-exports`、`GET /log-exports/{id}` (`:25-36`) | insert job，查 job 状态。 | 短事务。 | queue index 对齐；下载前要校验 job 状态和文件路径。 |
| `GET /log-exports/{id}/download` (`:38-49`) | HTTP 端点只查 job、检查 success、校验文件路径并返回 `FileResponse`；keyset `(server_ts,id)`、1000/batch 过滤发生在 `log_export_worker.py` 的文件生成阶段，不在 download 请求 SQL 中。 | HTTP 只读；worker 每批短 session；文件写盘。 | worker keyset 优于深 OFFSET；HTTP 下载和后台生成要分开压测，大范围仍受 IO/磁盘/网络影响，未实测吞吐。 |

## 7. 索引对齐摘要

1. **对齐较好**：version latest (`platform,version_code`)、published config package partial unique、export/parse job queue (`status,created_at`)、usage 的 package/device/time 前缀、事件按 package/time 的常见列表。
2. **部分对齐**：多数 log/metrics 查询以 package/time 开始，因此有选择性时可用；但 status、failure category、target、JSON payload 字段多在后续过滤，不能仅凭已有索引宣称稳定。
3. **明显缺口/风险**：无日期的 summary/filter-options/config history；JSONB 字段抽取与 distinct/group；metrics 多 scalar 子查询；所有 count + page 双查询；深 OFFSET；导出前导 wildcard；发布/rollback 在 COS 网络调用期间持有 DB 事务和 package advisory lock。
4. **分区主键事实**：`sdk_events` 主键包含 `server_ts`，因此单独按 `id` 不能完成全局 PK lookup；详情路径需要事件时间键或额外定位逻辑。

## 7.1 风险优先级

| 优先级 | 风险 | 是否已测 |
| --- | --- | --- |
| 高 | Dashboard summary 的 SQL 没有外层 WHERE，存在全历史分区扫描；metrics overview 多 scalar 重复扫描；publish/rollback 在 COS 网络期间持有 DB 事务和 advisory lock。 | SQL 形状已核对；生产耗时未本次复现。 |
| 高 | events/log summary/details、usage 31 天 latest、metrics 分组的 count + page/深 OFFSET 在增长数据上可能出现重复扫描、排序或 join 放大。 | 静态判断；未生产压测。 |
| 中 | filter-options 全量 distinct、全量配置历史无分页、前导 wildcard package 搜索、MV 每 5 分钟刷新与查询竞争。 | SQL/调度已核对；未测大数据量。 |
| 中 | 解析 stage 绑定/CPU timeout、导出 worker 磁盘/网络、COS reconcile 外部请求。 | 既有 docs 记录了部分解析超时；其余未本次实测。 |
| 低 | version latest、job claim、package profile/preference PK/upsert、单事件详情等已有 PK/前缀索引路径。 | 结构已核对；仍未宣称 P99。 |

## 8. 数据规模与安全验证方案

本次不连接生产。上线前应在脱敏独立副本或合成代表性数据上逐项验证：

```sql
EXPLAIN (COSTS, VERBOSE, FORMAT JSON) <代表性 SELECT>;
```

代表性集合至少包括：dashboard summary 当前/昨日、overview 的最大合法日期窗口、events 深页、log summary/details、usage 31 天 latest window、metrics failure/config/target、filter-options、前导 wildcard package 搜索、导出 keyset 首批/末批。测试数据应覆盖最近分区、90 天边界、一个事件多 decode record、多个 package/device/config、空结果和大结果。

验证时设置会话级 `statement_timeout`，先看 plan 再在副本执行 `EXPLAIN (ANALYZE, BUFFERS)`；不要在生产执行无上限 `ANALYZE` 或长时间 refresh。记录 planning/execution time、实际行数、shared hit/read、sort/hash spill、分区裁剪和连接池占用。发布/rollback 另测 COS 慢、失败重试、锁等待和事务持续时间。

## 9. 与 admin 登录变更的边界

本审计同时新增独立 admin password login，但不改变 SDK 写入鉴权和业务 SQL：固定用户名 `admin` 使用独立 scrypt hash；opaque session 只在单进程内存保存，8 小时绝对 TTL，重启失效；Cookie、CSRF、Origin、失败限流和 legacy Bearer 兼容见代码与测试。未引入 Redis/session 表，也不把 `ADMIN_TOKEN`、SDK token 或 SDK 写入 limiter 作为登录凭据/限流器。

健康检查只返回 status，不能作为登录成功证据；本地验收必须同时证明 `/auth/me`、受保护 API、刷新保会话、logout 后 API 401 以及 CSRF/Origin 拒绝行为。

## 10. 未完成/不应从本文推断的事项

- 当前基线没有本次生产 overview 超时的可逐行复核原始记录；不得宣称已用生产查询复现。
- 未在生产执行 EXPLAIN、刷新 MV、分区 apply、导出或解析任务。
- 未根据静态风险擅自新增索引、改统计口径、改分页语义或改留存策略。
- 单实例内存 session 不适用于多实例横向扩展；未来扩展必须单独设计共享 session store 与密钥/会话治理。
