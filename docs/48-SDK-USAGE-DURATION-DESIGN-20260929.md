# SDK 使用时长上报与后台查询设计

> 状态：已实施，待验收
> 日期：2026-09-29
> 范围：后端 SDK API、Admin API、数据库与接口文档；不包含前端页面

## 1. 背景与目标

SDK 在运行期间约每 1～2 分钟上报一次本阶段产生的使用时长。服务端需要保存每次上报，并向后台提供按包名、设备、版本和 UTC+8 日期范围查询的汇总与分页明细。

本功能的目标是：

1. 提供独立的 SDK 使用时长上报接口；
2. 使用独立数据表保存高频时长记录，避免影响现有日志和点击事件；
3. 提供带 Admin Token 鉴权的后台查询接口；
4. 保证汇总与明细应用完全相同的筛选条件；
5. 沿用项目现有写接口限流、包名规范化和 UTC+8 业务时间规则。

本次不增加前端页面、异步汇总表、数据归档、自动清理或导出功能。

## 2. 已确认的业务语义

- `duration_s` 由 SDK 计算并上报，单位为秒；
- `duration_s` 表示设备截至本次上报的累计 SDK 使用时长；同一设备在查询窗口内只取最新一条记录；
- SDK 预计每 1～2 分钟上报一次；
- 请求不携带客户端时间戳，记录时间使用服务器接收时间；
- 请求不携带 `report_id`，因此 SDK 超时重试可能形成重复记录，本期接受该行为；
- SDK 上报接口不使用 `SDK_CONFIG_TOKEN`，但必须使用现有写接口限流；
- SDK 上报响应只返回接收结果，不回显设备信息；
- 后台查询同时返回历史上报明细，以及按“包名 + 最新设备状态”计算的汇总。

## 3. 方案选择

### 3.1 方案比较

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| 复用 `sdk_events.payload` | 改动少 | 高频数据与日志、点击混合；JSON 聚合与版本筛选成本较高 | 不采用 |
| 新建 `sdk_usage_durations` 表 | 字段类型明确；索引和聚合独立；不影响现有事件 | 需要新增模型和迁移 | 采用 |
| 扩展 `sdk_events` 通用列 | 元数据统一 | 扩大现有日志、点击的变更和回归范围 | 不采用 |

### 3.2 最终方案

新增独立表、SDK 写接口和 Admin 读接口。写入路径保持同步单条插入；查询直接基于明细表聚合。当前规模不引入额外汇总表。

## 4. SDK 上报接口

### 4.1 请求

```http
POST /api/v1/usage-duration
Content-Type: application/json
```

请求示例：

```json
{
  "package_name": "com.example.app",
  "device_id": "device-001",
  "device_model": "iPhone13,2",
  "os": "17.5.1",
  "ver": "1.0",
  "sdk_version": "1.0.3",
  "duration_s": 60
}
```

### 4.2 字段约束

| 字段 | 类型 | 必填 | 约束 |
|---|---|---:|---|
| `package_name` | string | 是 | 1～255；复用现有包名规范化规则 |
| `device_id` | string | 是 | 1～64 |
| `device_model` | string | 是 | 1～100 |
| `os` | string | 是 | 1～50 |
| `ver` | string | 是 | 应用版本，1～50 |
| `sdk_version` | string | 是 | 1～20 |
| `duration_s` | integer | 是 | `1～3600` 秒，浮点数不可接受 |

请求不接受 `timestamp` 和 `report_id`。

### 4.3 鉴权、限流和来源信息

- 不要求 `SDK_CONFIG_TOKEN`；
- 使用现有 `write_limiter`；
- 保存 `request.client.host` 和 `User-Agent`，行为与现有日志、点击上报保持一致；
- 不在应用层自行信任客户端传入的 IP 字段。

### 4.4 响应

成功响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "accepted": 1,
    "rejected": 0
  }
}
```

错误规则：

- 请求字段或数值校验失败：HTTP 422，不写入数据库；
- 触发限流：沿用项目现有限流响应；
- 数据库写入失败：回滚事务并返回 HTTP 500，不返回内部异常详情。

## 5. 数据库设计

新增表 `sdk_usage_durations`：

| 字段 | 数据库类型 | 约束或说明 |
|---|---|---|
| `id` | `BIGINT` | 自增主键 |
| `package_name` | `VARCHAR(255)` | 非空 |
| `device_id` | `VARCHAR(64)` | 非空 |
| `device_model` | `VARCHAR(100)` | 非空 |
| `os` | `VARCHAR(50)` | 非空 |
| `app_version` | `VARCHAR(50)` | 非空；对应 API 字段 `ver` |
| `sdk_version` | `VARCHAR(20)` | 非空 |
| `duration_s` | `INTEGER` | 非空；检查约束 `1～3600` |
| `server_ts` | `TIMESTAMPTZ` | 非空；默认数据库当前时间 |
| `ip` | `INET` | 可空 |
| `user_agent` | `TEXT` | 可空 |

索引：

1. `server_ts DESC`；
2. `(package_name, server_ts DESC)`；
3. `(package_name, device_id, server_ts DESC)`。

迁移要求：

- 更新 `scripts/init_db.sql`，保证新环境直接具备该表；
- 新增可重复执行的独立生产迁移脚本；
- 使用 `CREATE TABLE IF NOT EXISTS`、条件式约束和 `CREATE INDEX IF NOT EXISTS`；
- 迁移不得修改或重写现有日志、点击、配置数据。

## 6. Admin 查询接口

### 6.1 请求

```http
GET /api/admin/usage-durations
Authorization: Bearer <ADMIN_TOKEN>
```

最新设备汇总接口为 `GET /api/admin/usage-durations/summary`；设备明细接口为
`GET /api/admin/usage-durations/devices`。汇总接口的 `package_name` 可留空查询全部包名，
`sort_by=device_model` 仅为兼容旧客户端，实际按包名排序。

查询参数：

| 参数 | 类型 | 说明 |
|---|---|---|
| `package_name` | string | 可选，完全匹配并按现有规则规范化 |
| `device_id` | string | 可选，完全匹配 |
| `sdk_version` | string | 可选，完全匹配 |
| `ver` | string | 可选，对应数据库 `app_version`，完全匹配 |
| `date_from` | date | 可选，必须与 `date_to` 成对出现 |
| `date_to` | date | 可选，必须与 `date_from` 成对出现 |
| `page` | integer | 默认 1，最小 1 |
| `page_size` | integer | 默认 20，范围 1～100 |

时间规则：

- 日期按 `Asia/Shanghai`（UTC+8）解释；
- 日期范围包含起始日和结束日，数据库查询使用转换后的 UTC 半开区间；
- 未传日期时，默认查询 UTC+8 当天；
- 单次日期跨度最多 31 个自然日，超出返回 HTTP 422；
- 明细按 `server_ts DESC, id DESC` 排序，保证相同时间下顺序稳定。

### 6.2 原始上报响应

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "summary": {
      "total_duration_s": 7260,
      "report_count": 103,
      "device_count": 8
    },
    "total": 103,
    "page": 1,
    "page_size": 20,
    "items": [
      {
        "id": 1001,
        "package_name": "com.example.app",
        "device_id": "device-001",
        "device_model": "iPhone13,2",
        "os": "17.5.1",
        "ver": "1.0",
        "sdk_version": "1.0.3",
        "duration_s": 60,
        "server_time": "2026-09-29T16:30:00+08:00",
        "ip": "203.0.113.10",
        "user_agent": "ExampleSDK/1.0.3"
      }
    ]
  }
}
```

汇总定义：

- `total_duration_s`：筛选范围内 `SUM(duration_s)`；无记录时为 0；
- `report_count`：筛选范围内记录数；
- `device_count`：筛选范围内 `COUNT(DISTINCT device_id)`；
- `total` 与 `report_count` 必须一致；
- `summary` 与 `items` 必须复用同一个筛选条件构造器。

所有响应时间使用项目现有 UTC+8 ISO 8601 序列化方法。

### 6.3 最新设备汇总响应

`/summary` 在时间范围内按 `(package_name, device_id)` 分区，使用
`server_ts DESC, id DESC` 选出每台设备的最新记录，再按包名聚合。即使同一包名包含多个
`device_model`，也只返回一个包名行；`device_model` 保留为 `null` 兼容字段。

```json
{
  "package_name": "com.example.app",
  "device_model": null,
  "device_count": 2,
  "total_duration_s": 1500,
  "average_duration_s": 750,
  "buckets": [
    {"key": "le_300", "count": 1, "share": 0.5},
    {"key": "301_600", "count": 0, "share": 0.0},
    {"key": "601_899", "count": 0, "share": 0.0},
    {"key": "ge_900", "count": 1, "share": 0.5}
  ],
  "last_report_at": "2026-09-30T10:00:00+08:00"
}
```

桶边界为 `≤300`、`301–600`、`601–899`、`≥900` 秒，比例以最新设备数为分母；无设备时
比例为 `null`。展开包名明细时不再按机型过滤，返回该包名的全部最新设备；如传入
`device_model`，仅作为兼容性的可选过滤条件。

## 7. 代码组织

预计变更范围：

- `backend/app/schemas/sdk_schemas.py`：新增 SDK 请求模型；
- `backend/app/models/usage_duration.py`：新增 ORM 模型；
- `backend/app/models/__init__.py`：按项目需要导出模型；
- `backend/app/api/sdk/usage_duration.py`：SDK 写接口；
- `backend/app/api/admin/usage_duration.py`：Admin 查询接口；
- `backend/app/services/usage_duration_service.py`：筛选、汇总和分页逻辑；
- `backend/app/sdk_main.py`、`backend/app/admin_main.py`：注册路由；
- `scripts/init_db.sql`：新环境表结构；
- `scripts/migrate_usage_durations.sql`：生产增量迁移；
- `backend/tests/`：接口、服务与迁移测试；
- 最新 API 对接文档：补充两个接口。

不修改前端目录，也不修改现有日志、点击和配置接口契约。

## 8. 测试与验收标准

### 8.1 SDK 写接口

- 合法请求写入一条记录并返回 `accepted: 1`；
- 包名按现有规则规范化；
- `duration_s=1` 和 `duration_s=3600` 可写入；
- `duration_s=0`、负数、浮点数和大于 3600 被拒绝；
- 任一必填字段缺失或超长被拒绝；
- 限流依赖被接入；
- IP、User-Agent 与服务器时间正确保存；
- 数据库异常触发回滚和 HTTP 500。

### 8.2 Admin 查询接口

- 缺少或错误 Admin Token 被拒绝；
- 包名、设备、SDK 版本、应用版本筛选分别生效；
- 多条件组合同时作用于汇总和明细；
- 日期条件按 UTC+8 边界转换；
- 未传日期时只查询 UTC+8 当天；
- 日期只传一端、结束早于开始、跨度超过 31 天时返回 HTTP 422；
- 分页、总数和倒序稳定；
- 无记录时汇总为 0、明细为空。

### 8.3 数据库与回归

- 初始化 SQL 包含新表、约束与索引；
- 增量迁移脚本可连续执行两次；
- 后端全部测试通过；
- 前端全部测试通过；
- 现有配置、点击、日志、分析和导出接口无回归。

## 9. 部署边界

本设计文档和后续实现提交不自动授权生产部署。完成代码、审查与测试后，应单独获得部署指令，并在部署前完成数据库与版本备份，再执行迁移、服务重启和生产冒烟测试。
