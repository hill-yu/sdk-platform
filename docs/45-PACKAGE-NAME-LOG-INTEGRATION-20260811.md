# SDK 埋点接口对接更新（2026-08-11）

## 1. 变更结论

SDK 事件链路统一使用 `package_name`，不再接受 `app_id`。数据库、后台查询、分析返回和前端筛选也使用同一字段名。

`POST /api/v1/log` 的单条日志中，`level` 和 `extra` 必传，`message` 可空。`extra` 是不透明字符串，可直接放入 SDK 生成的埋点内容；服务端不将它解析成 JSON 对象。

## 2. 日志上报

```http
POST /api/v1/log
Content-Type: application/json
```

```json
{
  "package_name": "com.example.app",
  "logs": [
    {
      "level": "info",
      "message": "埋点",
      "extra": "{ouoghaougoagahdgjalglauoi|dlaugouojlJ}"
    }
  ]
}
```

| 字段 | 类型 | 必传 | 规则 |
|---|---|---|---|
| `package_name` | string | 是 | 1～255 字符，按系统包名规则校验 |
| `device_id` | string/null | 否 | 最大 64 字符 |
| `sdk_version` | string | 否 | 最大 20 字符 |
| `logs` | array | 是 | 1～100 条 |
| `logs[].level` | string | 是 | `debug` / `info` / `warn` / `error`，大小写不敏感 |
| `logs[].extra` | string | 是 | 任意字符串，不做 JSON 解析或格式限制 |
| `logs[].message` | string/null | 否 | 缺省或 `null` 按 `""` 保存；最大 10000 字符 |
| `logs[].tag` | string/null | 否 | 最大 100 字符 |
| `logs[].timestamp` | integer/null | 否 | 毫秒时间戳 |

成功响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {"accepted": 1, "rejected": 0}
}
```

`extra` 传对象、数组、数字或 `null` 均返回 HTTP 422。传入旧字段 `app_id` 而缺少 `package_name` 也返回 HTTP 422。

## 3. 点击上报

```json
{
  "package_name": "com.example.app",
  "device_id": "device-001",
  "events": [
    {
      "type": "click",
      "page": "home",
      "element": "confirm_button",
      "extra": {"source": "sdk"}
    }
  ]
}
```

`POST /api/v1/click` 的 `package_name` 必传，且不接受 `app_id`。注意：点击事件的 `events[].extra` 仍为 JSON 对象，只有日志接口的 `logs[].extra` 改为必填字符串。

## 4. Admin 事件查询

```http
GET /api/admin/events?event_type=log&package_name=com.example.app&log_level=info&page=1&page_size=20
Authorization: Bearer <ADMIN_TOKEN>
```

响应事件项返回 `package_name` 和 `sdk_version`，不再返回 `app_id`。前端独立“日志查看”页固定传 `event_type=log`，并支持按包名、设备、日期和日志级别筛选。

`log_level` 可省略；传值时只能是 `debug`、`info`、`warn`、`error`，非法值返回 HTTP 422。分页参数 `page` 从 1 开始，`page_size` 范围为 1～100。Admin Token 必须放在 `Authorization: Bearer <ADMIN_TOKEN>` 请求头中，不得放在 URL。

单条日志的完整 `extra` 位于响应项的 `payload.extra`。后台详情区原样展示该字符串，并提供复制操作，不会将其解析成键值对象或截断后再复制。

## 5. Admin 日志解析统计

日志上报成功后，后端会保留原始事件，并对 `payload.extra` 中的字符串做异步解析，解析结果写入 `sdk_log_decodes`。解析只针对日志 `extra` 原始字符串，不改变 `sdk_events.payload`。

### 5.1 时间和筛选口径

- 业务日期统一按 `Asia/Shanghai`（UTC+8，北京时间）解释。
- `date_from`、`date_to`、`date` 都表示北京时间自然日，不是 UTC 日期；汇总接口两端包含。单日 `2026-08-17` 映射为 `[2026-08-16T16:00:00Z, 2026-08-17T16:00:00Z)`，返回时间示例为 `2026-08-17T09:30:00+08:00`。
- `package_name`、`device_id`、`log_level` 都是完全匹配。
- API 对外展示的时间使用 UTC+8；数据库仍保存绝对时间。

### 5.2 汇总接口

```http
GET /api/admin/log-analysis/summary?date_from=2026-08-17&date_to=2026-08-17&package_name=com.example.app&page=1&page_size=20
Authorization: Bearer <ADMIN_TOKEN>
```

汇总维度为北京时间日期和包名。核心指标包括：

| 字段 | 说明 |
|---|---|
| `user_count` | 去重设备数 |
| `flow_count` | 解析成功的流程日志数 |
| `expected_click_count` | 解析出的计划点击数总和 |
| `actual_click_count` | 解析出的实际点击数总和 |
| `ad_click_count` | 广告区域点击数总和 |
| `average_duration_ms` | 有耗时样本时的平均耗时，单位 ms；无样本时为 `null` |
| `duration_sample_count` | 参与平均耗时的非空耗时样本数 |
| `success_rate` | 成功样本占比；无样本时为 `null` |
| `parse_failure_count` | `failed + unsupported` 的解析失败数量 |

### 5.3 明细和详情

```http
GET /api/admin/log-analysis/details?date=2026-08-17&package_name=com.example.app&page=1&page_size=20
Authorization: Bearer <ADMIN_TOKEN>
```

明细列表用于查看解析后的每条记录。单条完整详情使用复合键查询：

```http
GET /api/admin/log-analysis/details/{event_id}?event_server_ts=<ISO_WITH_TIMEZONE>&record_index=0
Authorization: Bearer <ADMIN_TOKEN>
```

只有单条详情返回原始 `extra`，用于和 `decoded_payload` 追溯比对。

### 5.4 资料和列配置

包名资料：

```http
PUT /api/admin/package-profiles/com.example.app
Authorization: Bearer <ADMIN_TOKEN>
Content-Type: application/json

{
  "alias": "测试包",
  "company": "测试公司",
  "account": "测试账户"
}
```

全局列配置：

```http
PUT /api/admin/log-analysis/columns
Authorization: Bearer <ADMIN_TOKEN>
Content-Type: application/json

{
  "columns": ["date", "package_name", "alias", "url", "user_count", "success_rate"]
}
```

列配置为全局配置，所有包名共用。`url` 是列配置中的列名，展示时对应汇总响应里的 `primary_url`。

### 5.5 重解析和历史回填

`POST /api/admin/log-analysis/reparse` 当前会校验日期、包名、状态和 `decoder_version_before` 筛选意图并创建重解析任务记录，方便审计和后续编排；任务表当前主要保存包名、时间范围、创建者和初始计数，历史数据实际重算仍使用脚本：

```bash
python scripts/backfill_log_decodes.py --date-from 2026-08-17 --date-to 2026-08-18 --package-name com.example.app
python scripts/backfill_log_decodes.py --date-from 2026-08-17 --date-to 2026-08-18 --package-name com.example.app --apply --confirm BACKFILL_LOG_DECODES
```

`date-to` 是排他边界。正式执行前必须先 dry-run，并确认扫描量、成功数、失败数和游标符合预期。

当前没有已验证的 reparse job 后台消费者；Admin 启动时的 pending 日志解析循环只处理普通日志解码占位记录。因此该接口返回 `pending` 只代表任务记录已创建，不代表重解析已经开始或完成。

## 6. 数据库升级

先停止 SDK 写入或进入维护窗口，备份后执行：

```bash
python scripts/migrate_event_package_name.py
python scripts/migrate_event_package_name.py --apply --confirm MIGRATE_EVENT_PACKAGE_NAME
```

第一条只生成预检计划，不写数据库。第二条在单个事务内完成列改名、字段扩容、索引和物化视图重建，并校验事件总数、主表、分区表与视图列。已迁移数据库重复执行时不会再修改结构。

日志解析功能还需要执行解析表和 UTC+8 物化视图迁移：

```bash
python scripts/migrate_log_analysis.py
python scripts/migrate_log_analysis.py --apply --confirm MIGRATE_LOG_ANALYSIS
```

该脚本会检查事件总数、非空 `extra` 数、分区行数、解析表、索引和物化视图定义。重复执行应保持无损、可重入。
