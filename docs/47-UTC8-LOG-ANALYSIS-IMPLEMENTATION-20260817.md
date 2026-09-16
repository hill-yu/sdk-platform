# UTC+8 日志解析实施记录

> 日期：2026-08-17
>
> 分支：`codex/utc8-log-analysis`
>
> 状态：本地候选基线，生产部署前必须重新执行迁移 dry-run、备份和小流量验收。

## 1. 范围

本次实现围绕 SDK 日志 `extra` 的解析、统计和后台查看，包含：

- 全项目业务日期按 UTC+8（北京时间）解释；
- 日志上传后异步解析 `payload.extra` 字符串，解析结果写入 `sdk_log_decodes`；
- Admin 增加日志解析汇总、明细、单条详情、包名资料、全局列配置和重解析任务接口；
- 前端日志页默认展示解析统计，保留原始日志列表切换；
- 生产迁移和历史回填采用脚本化、可重复执行的门禁流程。

不包含：

- 生产数据库操作；
- 自动消费 `sdk_log_reparse_jobs` 的后台 worker；
- 对配置发布接口的任何调用。

## 2. 时间和筛选约定

| 项目 | 约定 |
|---|---|
| 业务日期 | UTC+8，北京时间自然日 |
| 数据库存储 | `server_ts`、`event_server_ts` 等仍保存绝对时间 |
| API 日期参数 | `date_from`、`date_to`、`date` 按北京时间解释 |
| API 时间输出 | 对外序列化为 UTC+8，前端展示 `YYYY-MM-DD HH:mm:ss` |
| 包名筛选 | 完全匹配，服务端统一规范化包名 |
| 设备筛选 | 完全匹配 |
| 日志级别筛选 | `debug` / `info` / `warn` / `error` 完全匹配 |

例如 `date_from=2026-08-17`、`date_to=2026-08-17` 的查询窗口是 `[2026-08-16T16:00:00Z, 2026-08-17T16:00:00Z)`；接口时间字段示例为 `2026-08-17T09:30:00+08:00`。

北京时间日期范围由统一工具计算，不直接使用 `date.today()` 推导业务日期。

## 3. 解析器

解析入口只处理 SDK 日志的 `payload.extra` 字符串。上传接口仍原样保存日志，解析过程不得改写原始 `sdk_events.payload`。

当前解析器版本为 `1.0.0`，由 `backend/app/services/flow_log_decoder.py` 的 `DECODER_VERSION` 定义。回填脚本会把该版本写入 `sdk_log_decodes.decoder_version`，便于后续按版本筛选历史重算范围。

解析状态：

| 状态 | 说明 |
|---|---|
| `pending` | 已占位，等待解析或重算 |
| `success` | 成功解析为结构化指标 |
| `unsupported` | `extra` 格式不支持 |
| `failed` | 解析过程失败 |

## 4. 数据库对象

迁移脚本：`scripts/migrate_log_analysis.py`

新增或确认以下对象：

| 对象 | 说明 |
|---|---|
| `sdk_log_decodes` | 解析后的明细记录，主键为 `event_id + event_server_ts + record_index` |
| `sdk_package_profiles` | 包名别名、公司、账户 |
| `sdk_admin_preferences` | 后台全局偏好，目前用于日志统计列配置 |
| `sdk_log_reparse_jobs` | 重解析任务记录 |
| `mv_daily_event_stats` | 北京时间日统计物化视图 |
| `mv_hourly_trend` | 北京时间小时趋势物化视图 |

迁移脚本会检查事件总数、非空 `extra` 数、分区行数、表、索引和物化视图摘要。第二次执行 `--apply` 必须保持可重入。

## 5. Admin API

以下接口均要求：

```http
Authorization: Bearer <ADMIN_TOKEN>
```

### 5.1 汇总

```http
GET /api/admin/log-analysis/summary?date_from=2026-08-17&date_to=2026-08-17&package_name=com.example.app&page=1&page_size=20&sort_by=date&sort_order=desc
```

主要响应字段：

| 字段 | 说明 |
|---|---|
| `date` | 北京时间日期 |
| `package_name` | 包名 |
| `alias` / `company` / `account` | 后台维护的包名资料 |
| `primary_url` | 汇总样本中的代表 URL；前端列名为 `url` |
| `url_count` | 去重 URL 数 |
| `user_count` | 去重设备数 |
| `flow_count` | 成功解析的流程数 |
| `expected_click_count` | 计划点击数总和 |
| `actual_click_count` | 实际点击数总和 |
| `ad_click_count` | 广告区域点击数总和 |
| `average_duration_ms` | 平均耗时，单位 ms |
| `success_rate` | 成功率，无样本为 `null` |
| `parse_failure_count` | `failed + unsupported` 数量 |

`average_duration_ms` 只对非空 `duration_ms` 样本计算，并配套 `duration_sample_count`；`success_rate` 只对有 `is_success` 的样本计算，并配套 `success_sample_count`。无有效样本时平均值和比率为 `null`，计数类指标为 `0`，客户端不得将 `null` 当成 0% 或 0 毫秒。

### 5.2 明细

```http
GET /api/admin/log-analysis/details?date=2026-08-17&package_name=com.example.app&page=1&page_size=20
```

列表返回解析后的结构化字段，不返回原始 `extra`。

### 5.3 单条详情

```http
GET /api/admin/log-analysis/details/{event_id}?event_server_ts=<ISO_WITH_TIMEZONE>&record_index=0
```

单条详情按复合键定位，返回完整 `decoded_payload` 和原始 `extra`。

### 5.4 包名资料

```http
GET /api/admin/package-profiles?package_name=com.example.app
PUT /api/admin/package-profiles/com.example.app
```

请求体：

```json
{
  "alias": "测试包",
  "company": "测试公司",
  "account": "测试账户"
}
```

三个字段均可置空。前端保存后会同步当前页相同包名的行。

### 5.5 全局列配置

```http
GET /api/admin/log-analysis/columns
PUT /api/admin/log-analysis/columns
```

请求体：

```json
{
  "columns": ["date", "package_name", "alias", "url", "user_count", "success_rate"]
}
```

列配置为全局配置。`date` 和 `package_name` 是前端强制保留列；服务端仍以自己的列目录为准校验。

### 5.6 重解析任务

```http
POST /api/admin/log-analysis/reparse
```

请求体示例：

```json
{
  "date_from": "2026-08-17",
  "date_to": "2026-08-17",
  "package_name": "com.example.app",
  "status": "failed",
  "decoder_version_before": "1.0.0"
}
```

当前接口会校验并接收范围、包名、状态和 `decoder_version_before` 筛选意图，但任务表主要保存包名、时间范围、创建者和初始计数；它只创建 `pending` 任务记录。历史数据实际重算仍通过 `scripts/backfill_log_decodes.py` 执行；不要把该接口当作已经自动触发后台 worker。

## 6. 历史回填

dry-run：

```bash
python scripts/backfill_log_decodes.py --date-from 2026-08-17 --date-to 2026-08-18 --package-name com.example.app
```

正式执行：

```bash
python scripts/backfill_log_decodes.py --date-from 2026-08-17 --date-to 2026-08-18 --package-name com.example.app --apply --confirm BACKFILL_LOG_DECODES
```

注意事项：

- `date-to` 是排他边界；
- 每批最多 500 条；
- 输出包含本批和累计的 `scanned`、`success`、`unsupported`、`failed` 与游标；
- 支持 `--status`、`--decoder-version-before`、`--cursor-ts`、`--cursor-id` 做安全续跑；
- 回填过程中会校验原始 payload 摘要，防止改写原始事件。

## 7. 本地验证记录

自动验证命令：

```powershell
py -m pytest -q backend/tests
npm --prefix frontend test -- --run
npm --prefix frontend run build
git diff --check
rg -n "date\.today\(|timezone\.utc|isoformat\(\)" backend/app
rg -n "flow_log_decoder|log-analysis|Asia/Shanghai" backend frontend scripts docs/40-LATEST-API-INTEGRATION-GUIDE-20260810.md docs/45-PACKAGE-NAME-LOG-INTEGRATION-20260811.md docs/47-UTC8-LOG-ANALYSIS-IMPLEMENTATION-20260817.md
```

执行结果：

| 检查项 | 状态 | 记录 |
|---|---|---|
| 后端测试 | 通过 | `py -m pytest -q backend/tests`，215 passed in 6.20s |
| 前端测试 | 通过 | `npm --prefix frontend test -- --run`，17 files / 106 tests passed |
| 前端构建 | 通过 | `npm --prefix frontend run build` 成功；仅保留既有 chunk size warning |
| diff 检查 | 通过 | `git diff --check` 退出码 0，仅提示 Windows 换行转换 warning |
| UTC 扫描 | 已检查 | 命中项包括绝对时间存储、客户端 epoch 转换、配置更新时间、解析时间和统一时区工具；业务日期使用 `app.core.timezone` 或 SQL `AT TIME ZONE 'Asia/Shanghai'` |
| 日志解析关键字扫描 | 通过 | 命中 `flow_log_decoder`、`log-analysis`、`Asia/Shanghai` 的后端、前端、脚本和文档位置 |

UTC 扫描判断：

- `backend/app/core/timezone.py` 是统一业务时区工具，允许使用 `timezone.utc` 做 UTC 边界转换，并通过 `Asia/Shanghai` 输出业务时间。
- `backend/app/api/sdk/click.py` 和 `backend/app/api/sdk/log.py` 对客户端毫秒时间戳使用 UTC，是绝对时间存储需要。
- `backend/app/services/config_service.py` 的草稿版本、更新时间、发布时间使用 UTC，是数据库审计时间。
- `backend/app/services/log_parse_service.py` 的 `parsed_at` 和无时区解析兜底使用 UTC，是解析记录绝对时间。
- `backend/app/services/log_analysis_service.py` 的 `date.isoformat()` 只用于返回已经按北京时间分组后的日期字符串。

## 8. 本地 PostgreSQL 迁移演练

本次按顺序实际尝试以下 4 条命令；前两条是迁移 dry-run/apply，后两条是北京时间单日回填 dry-run/apply。回填的 `--date-to` 是排他边界。

```powershell
py scripts/migrate_log_analysis.py
py scripts/migrate_log_analysis.py --apply --confirm MIGRATE_LOG_ANALYSIS
py scripts/backfill_log_decodes.py --date-from 2026-08-17 --date-to 2026-08-18
py scripts/backfill_log_decodes.py --date-from 2026-08-17 --date-to 2026-08-18 --apply --confirm BACKFILL_LOG_DECODES
```

执行记录：

| 项目 | 状态 | 记录 |
|---|---|---|
| 迁移 dry-run | 未执行 | 当前 shell 未设置 `DATABASE_URL`；命令退出并提示必须设置 `DATABASE_URL` |
| 迁移 apply | 未执行 | 同上；未触达数据库、事务和写入 |
| 回填 dry-run | 未执行 | 使用本地默认数据库配置连接时返回 `ConnectionRefusedError` |
| 回填 apply | 未执行 | 同上；未触达回填事务 |
| 事件总数 | 未记录 | 本机未发现 PostgreSQL 服务 |
| 非空 `extra` 数 | 未记录 | 无本地 PostgreSQL 连接 |
| 分区行数 | 未记录 | 无本地 PostgreSQL 连接 |
| 表、索引、视图 | 未记录 | 无本地 PostgreSQL 连接 |

本次所需环境变量为 `DATABASE_URL`；回填还需要可连接的本地 PostgreSQL 和已完成解析表迁移。apply 命令虽按要求尝试，但由于环境门禁/连接失败均未执行写入。如本地没有可用 PostgreSQL，必须记录为未执行，不得伪造迁移结果。

## 9. 端到端 smoke

专用包名建议：`com.example.utc8.smoke`。不得使用生产包名。

验收步骤：

1. 通过 `POST /api/v1/log` 写入一条固定 H1 `extra` 的日志；
2. 确认 SDK API 快速返回 `accepted`；
3. 等待异步解析循环把记录写入 `sdk_log_decodes` 且状态为 `success`；
4. 用北京时间日期和包名查询 summary；
5. 下钻 details；
6. 用复合键查询单条 detail，并确认可追溯到原始 `extra`；
7. 更新并清空包名资料；
8. 修改全局列配置后恢复默认；
9. 写入跨 UTC 16:00 的两个样本，确认归属不同北京时间日期；
10. 删除 smoke 事件、解析结果、包名资料和偏好测试数据；
11. 确认整个过程未调用配置发布接口。

执行结果：

| 项目 | 状态 | 记录 |
|---|---|---|
| smoke | 未执行 | 依赖本地 PostgreSQL 迁移和本地 API 服务；当前 `DATABASE_URL` 缺失，未构造 smoke 数据 |
| 清理 | 未执行 | 未写入 smoke 数据，无需清理 |
| 配置发布接口 | 未调用 | 本验收不需要调用配置发布 |

## 10. 生产部署门禁

生产部署只能在用户另行明确授权后执行。推荐顺序：

1. 备份数据库，并验证备份可恢复；
2. 保存当前后端 commit、前端 dist、环境变量快照和物化视图定义；
3. 在生产库执行 `scripts/migrate_log_analysis.py` dry-run；
4. 进入维护窗口，停止或限流解析写入；
5. 执行 `scripts/migrate_log_analysis.py --apply --confirm MIGRATE_LOG_ANALYSIS`；
6. 部署后端；
7. 执行健康检查和 Admin Token 鉴权检查；
8. 部署前端；
9. 用专用测试包名做小流量 smoke；
10. 对小日期范围执行历史回填 dry-run 和 apply；
11. 核对 summary/details/detail 指标；
12. 分批扩大回填范围；
13. 保留旧 commit、旧 dist、数据库备份和旧物化视图定义，满足回滚需要。

回滚时优先恢复应用版本；如迁移已写入生产库，需要基于部署前备份和变更窗口内新增数据情况制定数据库回滚方案，不能直接执行破坏性脚本。
