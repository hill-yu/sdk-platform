# SDK 原始日志批量导出设计

## 1. 目标

在现有独立日志查看页增加批量导出能力：管理员可检索并选择多个 `package_name`，结合页面当前的设备 ID、日志级别和日期条件，创建后台异步任务并下载原始日志 CSV。

本次只实现导出闭环，不解析 `extra`，不调整 SDK 日志上报协议，不扩展日志分析指标。

## 2. 已确认需求

- 导出内容：原始日志；
- 文件格式：CSV；
- 包名：支持关键字检索、多个包名选择，导出查询使用完全匹配；
- 筛选范围：应用日志页面当前的设备 ID、日志等级、开始日期和结束日期；
- 处理方式：数据库任务表持久化任务，独立 Worker 异步生成文件；
- `extra`：按数据库中的原始字符串导出，不解析、不改写；
- 时间：CSV 中的 `client_ts`、`server_ts` 转换为 UTC+8。

## 3. 明确不做

- 不引入 Redis、Celery、RabbitMQ 等新基础设施；
- 不做导出任务历史列表、任务删除、重试按钮和并发配额；
- 不做定时清理、文件保留天数配置和对象存储上传；
- 不支持 Excel、ZIP 或解析后日志；
- 不修改现有 `/api/v1/log` 和 `/api/admin/events` 契约；
- 不顺带实现当前尚未落地的日志词库解析功能。

## 4. 用户流程

1. 管理员进入“日志查看”页，在包名选择器输入关键字；
2. 前端查询数据库中已有日志包名并展示候选项；
3. 管理员勾选一个或多个包名，填写其他筛选条件；
4. 点击“批量导出 CSV”；
5. 后端校验条件并写入一条 `pending` 任务，立即返回任务 ID；
6. 独立 Worker 领取任务，以固定批次读取日志并流式写入 CSV；
7. 前端每 2 秒查询任务状态；
8. 状态变为 `success` 后显示下载按钮；状态变为 `failed` 时显示失败原因。

页面查询日志仍使用单个包名的现有接口；多选包名只用于批量导出，避免改变现有列表查询行为。

## 5. 数据模型

新增表 `sdk_log_export_jobs`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID | 任务 ID，同时用于生成不可预测的文件名 |
| `status` | VARCHAR(20) | `pending`、`running`、`success`、`failed` |
| `package_names` | JSONB | 非空包名字符串数组 |
| `device_id` | VARCHAR(64) | 可空，完全匹配 |
| `log_level` | VARCHAR(10) | 可空，限定 `debug/info/warn/error` |
| `date_from` | DATE | 可空，按 UTC+8 自然日解释 |
| `date_to` | DATE | 可空，按 UTC+8 自然日解释且包含当天 |
| `file_path` | TEXT | 成功后保存服务端绝对路径，不返回给前端 |
| `row_count` | BIGINT | 实际写入数据行数 |
| `error_message` | TEXT | 失败摘要，不包含 Token 或 SQL |
| `created_at` | TIMESTAMPTZ | 创建时间 |
| `started_at` | TIMESTAMPTZ | Worker 开始处理时间 |
| `finished_at` | TIMESTAMPTZ | 成功或失败时间 |

索引仅增加 `(status, created_at)`，供 Worker 领取最早的待处理任务。

## 6. API 契约

所有接口复用现有 `Authorization: Bearer <ADMIN_TOKEN>` 鉴权。

### 6.1 检索包名

```http
GET /api/admin/log-packages?keyword=tech&limit=20
```

从 `sdk_events` 中查询 `event_type='log'` 的去重包名。`keyword` 使用包含匹配，仅用于候选检索；结果按包名升序返回，`limit` 范围为 1～50。

```json
{
  "code": 0,
  "data": {
    "items": ["com.techflow.note", "com.techflow.reader"]
  }
}
```

### 6.2 创建导出任务

```http
POST /api/admin/log-exports
Content-Type: application/json
```

```json
{
  "package_names": ["com.example.app", "com.techflow.note"],
  "device_id": "device-1",
  "log_level": "info",
  "date_from": "2026-08-01",
  "date_to": "2026-08-28"
}
```

规则：

- `package_names` 必须包含 1～50 个非空值，后端去除首尾空格并去重；
- `device_id` 为空字符串时归一化为 `null`；
- `log_level` 只接受四个现有等级；
- 日期可空；两者同时存在时 `date_from <= date_to`；
- 创建接口不统计日志数量，也不等待文件生成。

成功返回 HTTP 200：

```json
{
  "code": 0,
  "data": {
    "id": "3f21f57d-9a85-4a69-a684-a7ff3ee26bc1",
    "status": "pending"
  }
}
```

### 6.3 查询任务状态

```http
GET /api/admin/log-exports/{job_id}
```

```json
{
  "code": 0,
  "data": {
    "id": "3f21f57d-9a85-4a69-a684-a7ff3ee26bc1",
    "status": "success",
    "row_count": 1520,
    "error_message": null,
    "created_at": "2026-08-28T10:00:00+08:00",
    "finished_at": "2026-08-28T10:00:08+08:00"
  }
}
```

不存在的任务返回 HTTP 404。响应不暴露 `file_path`。

### 6.4 下载 CSV

```http
GET /api/admin/log-exports/{job_id}/download
```

- 仅 `success` 状态允许下载；
- 其他状态返回 HTTP 409；
- 文件不存在返回 HTTP 404；
- 响应使用 `text/csv; charset=utf-8` 和附件文件名；
- 文件名格式：`sdk-logs-<任务ID>.csv`。

## 7. Worker

新增独立入口 `python -m app.workers.log_export_worker`，生产环境作为单独 systemd 服务运行。

Worker 循环逻辑：

1. 开启短事务，通过 `FOR UPDATE SKIP LOCKED` 领取最早的 `pending` 任务；
2. 将任务更新为 `running` 并提交；
3. 按任务条件查询 `sdk_events`，固定 `event_type='log'`，包名使用 `IN (...)`；
4. 以 `(server_ts, id)` 升序和每批 1000 条的游标方式读取；
5. 使用 Python 标准库 `csv` 写入临时文件；
6. 完成后原子重命名为正式 CSV，并更新 `success`、`file_path`、`row_count`；
7. 出现异常时删除临时文件并更新 `failed` 和失败摘要；
8. 无任务时等待 2 秒继续轮询。

Worker 和 Admin API 共用现有 PostgreSQL 配置，不占用 Web 请求生命周期。使用数据库锁后，即使误启动两个 Worker，同一任务也只会被一个进程领取。

## 8. CSV 规则

表头固定为：

```text
id,package_name,device_id,sdk_version,level,tag,message,extra,client_ts,server_ts
```

- 使用 UTF-8 BOM，便于 Windows Excel 正确识别中文；
- 使用标准 CSV 引号和换行转义；
- `level/tag/message/extra` 分别取自 `payload` 对应字段；
- `extra` 若为字符串则原样写入；历史异常数据不是字符串时以紧凑 JSON 写入，避免导出任务失败；
- 时间转换为 `Asia/Shanghai`，格式 `YYYY-MM-DD HH:mm:ss`，空值输出空字符串；
- 文本以 `=、+、-、@` 开头时加单引号，防止表格软件将日志内容当作公式执行。

日期筛选按 UTC+8 自然日换算为数据库 UTC 边界。例如 `2026-08-28` 对应 `[2026-08-27T16:00:00Z, 2026-08-28T16:00:00Z)`。

## 9. 前端调整

在现有 `LogViewer.vue` 中完成，不新增独立页面：

- 包名输入区域增加“导出包名”多选控件；
- 输入关键字后调用包名接口，候选项支持勾选；
- 已选包名以标签展示并可移除；
- 点击“批量导出 CSV”时复用当前设备、等级和日期筛选值；
- 创建后显示当前任务状态和行数；
- `pending/running` 时每 2 秒轮询；
- `success` 时显示下载按钮；
- 页面卸载或任务终态时停止轮询。

按钮在未选择包名或创建请求进行中时禁用。下载通过带 Admin Token 的 Axios 请求获取 Blob，再由浏览器保存，不能直接跳转裸 URL。

## 10. 配置与部署

只新增一个环境变量：

```dotenv
LOG_EXPORT_DIR=/www/wwwroot/sdk-api/exports
```

目录必须由部署用户创建并赋予 Worker 写权限、Admin API 读权限。部署新增 `sdk-log-export-worker.service`，与现有服务使用相同代码目录、虚拟环境和 `.env`。

数据库迁移通过幂等 SQL 创建任务表和索引；`scripts/init_db.sql` 同步更新，保证新环境直接可用。

## 11. 验收标准

1. 包名关键字能返回实际存在日志的候选包名；
2. 可选择多个包名创建异步任务，接口立即返回 `pending`；
3. Worker 能将任务推进为 `running` 后再到 `success` 或 `failed`；
4. CSV 只包含选中包名且满足当前设备、等级和日期条件的原始日志；
5. `extra` 内容不经过词库解析；
6. CSV 时间为 UTC+8，中文和包含逗号、引号、换行的内容可正确读取；
7. 未鉴权不能创建、查询或下载任务；
8. 非成功任务不可下载，API 不泄露服务器文件路径；
9. 现有日志查询、详情、配置管理和 SDK API 行为不变。
