# 日志指标、设备时长与 H1 导出实施与运维说明

日期：2026-09-30

本文记录仓库中已实现的接口、数据口径、独立解析 worker、性能基准和发布/回滚操作。本文不包含密码、Token 或生产日志。

## 当前状态与部署事实

截至本文日期，仓库包含显式解析任务、结构化 H1/点击指标、设备时长查询和 H1 混合导出实现，以及对应迁移和测试。现有生产部署基线仍以 `docs/42-PRODUCTION-SYSTEM-API-BASELINE-20260811.md` 和既有 systemd 配置为准；本次新增的解析 worker、字段和前端构建在完成正式发布前均视为“待部署”，不能据此推断服务器已经运行新版本。

当前仓库事实：

- API 进程仍分别使用 SDK API `8100` 和 Admin API `8101` 的部署拓扑。
- 既有导出 worker 的部署路径是 `/www/wwwroot/sdk-api/backend`，虚拟环境解释器是 `/www/wwwroot/sdk-api/backend/venv/bin/python`。
- 新解析 worker unit 位于 `deploy/systemd/sdk-log-parse-worker.service`，沿用上述路径和 `www` 用户示例；安装前必须按服务器实际路径、用户和 `.env` 调整。
- 新 worker 未在本次变更中启动、部署或合并。

## API

所有 Admin 路由都需要现有 Admin Token，并使用 `{"code": 0, "data": ...}` 响应包装。

### 解析任务

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/admin/log-analysis/parse-jobs` | 创建显式解析任务 |
| `GET` | `/api/admin/log-analysis/parse-jobs/{id}` | 查询任务状态与进度 |
| `POST` | `/api/admin/log-analysis/parse-jobs/{id}/cancel` | 请求取消任务 |
| `GET` | `/api/admin/log-analysis/coverage` | 按任务状态统计覆盖 |

创建请求要求 `package_name`、`date_from`、`hour_from`、`date_to`、`hour_to`，拒绝额外字段。时间按北京时间（UTC+8）解释为连续半开区间：

```text
[date_from hour_from:00:00, date_to hour_to+1:00:00)
```

范围最大 7 个连续自然日。任务创建时保存 `snapshot_end = min(range_end, now)`，因此不会追赶创建后的新日志。全局同时只允许一个 `pending/running` 解析任务；worker 按 `(server_ts, event_id)` 游标、每批最多 200 条、最多 3 个解析进程处理，并在成功后原子替换目标范围的正式 H1 与点击结果。

### 结构化指标

以下接口都要求完整的包名和 UTC+8 日期/小时范围：

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/admin/log-analysis/metrics/overview` | 总体指标 |
| `GET` | `/api/admin/log-analysis/metrics/configs` | `config_id` 分组与占比 |
| `GET` | `/api/admin/log-analysis/metrics/targets` | 网页元素/广告目标维度 |
| `GET` | `/api/admin/log-analysis/metrics/failures` | 失败原因下钻，可选 `target_kind`、`config_id` |
| `GET` | `/api/admin/log-analysis/metrics/h1` | H1 明细分页 |

指标口径固定如下：

- 计划声明数来自 H1 声明；实际点击数来自 `pa.did_click=true`；响应成功数来自 `navigation_code=1`，三者不互相替代。
- 失败定义为 `navigation_code IS DISTINCT FROM 1`；失败原因优先取 `reason`、`error_detail`、`navigation_result`，都为空时为“未知原因”。
- `config_id` 占比为该组 H1 声明数除当前范围全部 H1 声明数，缺失值计入“未知”。无数据时返回/显示 `-`。
- 插屏关闭成功占比为 `SUM(close_count) / SUM(presentation_count)`，非关闭点击占比为 `SUM(click_count) / SUM(presentation_count)`；分母为 0 时为 `null`，不显示 `0%`。

### 设备时长

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/admin/usage-durations/summary` | 按包名+机型汇总 |
| `GET` | `/api/admin/usage-durations/devices` | 展开某包名+机型的设备明细 |

默认范围为最近 3 个北京时间自然日；可传包名、日期/小时、分页和白名单排序参数。每台设备只取范围内最新的 `server_ts` 记录，汇总时长是这些最新 `duration_s` 之和，平均时长为四舍五入后的汇总时长除设备数。分布边界为 `<=300`、`300< x <=600`、`600< x <900`、`>=900` 秒，四档数量之和必须等于设备数。去重、最新记录选择和聚合均在数据库完成。

### H1 混合导出

现有日志导出接口 `POST /api/admin/log-exports` 接受 `export_mode=raw|h1`，默认 `raw`；查询和下载接口保持 `/api/admin/log-exports/{id}` 与 `/api/admin/log-exports/{id}/download`。H1 CSV 列为：

```text
event_id,server_time,package_name,device_id,device_model,os,ver,
sdk_version,level,record_type,record_index,content
```

有 H1 的原始事件每条 H1 输出一行，`record_type=h1`、`record_index` 从 1 开始；无 H1 时保留一行 `record_type=raw` 的完整 `extra`。CSV 会转义换行、引号、逗号并保护公式注入。导出必须复用页面已应用的包名、日期、小时、SDK、设备和日志级别筛选。

## 独立 worker

安装前先确认生产路径和用户，不要直接复制示例中的占位路径：

```bash
sudo install -m 0644 deploy/systemd/sdk-log-parse-worker.service \
  /etc/systemd/system/sdk-log-parse-worker.service
sudo systemctl daemon-reload
sudo systemctl enable --now sdk-log-parse-worker
sudo systemctl status sdk-log-parse-worker --no-pager
```

unit 的资源与可靠性约束为 `CPUQuota=300%`、`MemoryMax=1536M`、`Nice=5`、`Restart=always`。`.env` 至少需要：

```dotenv
LOG_PARSE_BATCH_SIZE=200
LOG_PARSE_CONCURRENCY=3
LOG_PARSE_MAX_DAYS=7
LOG_PARSE_LEASE_SECONDS=60
```

日志只通过 systemd 查看：

```bash
sudo journalctl -u sdk-log-parse-worker -n 100 --no-pager
```

worker 收到 `SIGTERM` 后在当前批次提交/释放租约后退出；异常任务会以脱敏错误摘要进入 `failed`，不发布暂存结果。

## 端到端性能基准

`scripts/benchmark_log_parse.py` 使用独立的 `__sdk_parse_benchmark__...` 包名，写入受控原始事件，调用真实 `create_parse_job()` 创建显式任务，启动真实 `run_worker_once()`，并轮询持久化任务直到 `success/failed/cancelled`。计时覆盖任务创建后的数据库读取、进程间解析、暂存写入、游标推进和正式结果替换；不是纯函数计时或伪造状态。

在临时 PostgreSQL 14.22 UTF-8/C/Asia Shanghai、6-core 本地验收环境执行：

```bash
python scripts/benchmark_log_parse.py --events 10000 --max-seconds 60
```

只有同时满足以下条件才会输出 `"passed": true` 并返回 0：任务状态为 `success`、`processed_count=10000`、失败 H1 数为 0、无 H1 事件数与输入一致、计时不超过 60 秒。超时、失败或计数不一致返回非零退出码。默认 finally 清理本次运行生成的唯一 benchmark 包名下的事件、任务和暂存/正式结果；需要调查时可显式使用 `--keep-data`，完成后应手工清理该独立包名。

本地实测记录：P0 批量写入优化后的同样本耗时 `75.023s`；P1 任务级进程池复用后耗时 `28.443s`。最终任务为 `success`，处理 `10000` 条原始事件，正式表核对得到 `19000` 条 H1、`47500` 条点击、`500` 条无 H1 fallback、`0` 条失败 H1，输出 `passed=true`。该结果仅代表上述本地 6-core 临时库，不代表生产同规格 4 vCPU 门禁已通过；生产性能、API 健康检查和 SDK 日志上报验证仍待执行。

同一收口批次的本地验证还包括：后端根目录限定测试集 `402 passed`，前端全量 `30 files / 169 tests`，`vue-tsc --noEmit`、生产构建和迁移双执行幂等检查通过。默认从 `backend` 目录运行的 pytest 收集仍受既有外部 `test_api2.py` 和根目录 `scripts` 导入问题影响，未将该命令误报为全量通过。

最后的任务快照复审修复后，独立复测耗时为 `34.538s`；该结果仍来自上述本地临时验收环境，不代表生产同规格门禁。

脚本不会自动部署、重启服务或写入业务包名。性能门禁应同时人工确认 SDK 健康接口和一笔测试日志上报成功。

## 迁移、发布、验收和回滚

发布前备份数据库、当前 release、前端 `dist`、systemd unit 和宝塔 Nginx 配置。迁移和发布顺序：

1. 在一次性数据库上执行新迁移两次，确认第二次幂等且对象没有重复。
2. 备份生产数据库和 release；执行迁移，保留新增表/字段。
3. 发布并重启 API，检查 `8100` SDK 健康接口和 `8101` Admin 健康接口。
4. 安装并启动解析 worker；用单包名、一小时范围创建小任务，确认终态和指标。
5. 发布前端 `dist`，验证原始日志、H1 导出、解析指标和设备时长。
6. 在同规格环境运行 10,000 条基准，并保存 JSON 输出和测试时间。

紧急回滚时先停止新 worker，再恢复上一版 API、前端和 systemd 配置；新增表和字段保留，不在回滚中删除。原始 `sdk_events` 和设备时长历史记录不得删除。恢复旧解析链路前，需按旧版本要求重建兼容占位数据，并验证原始事件数量不变。

任何真实 Token、数据库密码、COS 密钥和生产日志只能通过服务器密钥管理或未入库的 `.env` 注入，不能写入本文档、示例 unit 或基准输出。
