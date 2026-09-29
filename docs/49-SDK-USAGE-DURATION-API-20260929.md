# SDK 使用时长接口对接文档

## SDK 上报

```http
POST /api/v1/usage-duration
Content-Type: application/json
```

该接口无需 `SDK_CONFIG_TOKEN`，但与其他 SDK 写接口共享按 IP 的写入限流。

请求字段：

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `package_name` | string | 是 | 1～255；服务端去除首尾空格并转为小写，且符合包名规则 |
| `device_id` | string | 是 | 1～64 |
| `device_model` | string | 是 | 1～100 |
| `os` | string | 是 | 1～50 |
| `ver` | string | 是 | 应用版本，1～50 |
| `sdk_version` | string | 是 | 1～20 |
| `duration_s` | integer | 是 | 1～3600 的整数秒数 |

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

PowerShell：

```powershell
$body = @{
  package_name = "com.example.app"
  device_id = "device-001"
  device_model = "iPhone13,2"
  os = "17.5.1"
  ver = "1.0"
  sdk_version = "1.0.3"
  duration_s = 60
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "https://api.example.com/api/v1/usage-duration" `
  -ContentType "application/json" `
  -Body $body
```

curl：

```bash
curl -X POST 'https://api.example.com/api/v1/usage-duration' \
  -H 'Content-Type: application/json' \
  -H 'User-Agent: ExampleSDK/1.0.3' \
  -d '{
    "package_name": "com.example.app",
    "device_id": "device-001",
    "device_model": "iPhone13,2",
    "os": "17.5.1",
    "ver": "1.0",
    "sdk_version": "1.0.3",
    "duration_s": 60
  }'
```

成功响应（HTTP 200）：

```json
{"code":0,"message":"ok","data":{"accepted":1,"rejected":0}}
```

服务端以接收时间记录 `server_ts`，并保存请求客户端 IP 与 `User-Agent`。请求不接受
`timestamp` 和 `report_id`。本期不提供幂等去重；SDK 因超时重试时，可能产生重复记录。

## Admin 查询

```http
GET /api/admin/usage-durations
Authorization: Bearer <ADMIN_TOKEN>
```

支持的查询参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `package_name` | string | 无 | 完全匹配；按 SDK 接口相同规则规范化 |
| `device_id` | string | 无 | 完全匹配 |
| `sdk_version` | string | 无 | 完全匹配 |
| `ver` | string | 无 | 对应数据库 `app_version`，完全匹配 |
| `date_from` | date | UTC+8 当天 | 必须与 `date_to` 成对提供 |
| `date_to` | date | UTC+8 当天 | 包含结束日 |
| `page` | integer | 1 | 最小值 1 |
| `page_size` | integer | 20 | 范围 1～100 |

日期按 `Asia/Shanghai`（UTC+8）解释，包含起始日和结束日，最多查询 31 个自然日。
数据库使用转换后的 UTC 半开区间。明细按 `server_ts DESC, id DESC` 排序。

PowerShell：

```powershell
$headers = @{ Authorization = "Bearer $env:ADMIN_TOKEN" }
Invoke-RestMethod `
  -Method Get `
  -Uri "https://admin.example.com/api/admin/usage-durations?package_name=com.example.app&date_from=2026-09-01&date_to=2026-09-29&page=1&page_size=20" `
  -Headers $headers
```

curl：

```bash
curl 'https://admin.example.com/api/admin/usage-durations?package_name=com.example.app&date_from=2026-09-01&date_to=2026-09-29&page=1&page_size=20' \
  -H 'Authorization: Bearer <ADMIN_TOKEN>'
```

成功响应（HTTP 200）：

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

`summary` 与 `items` 使用完全相同的筛选条件。无记录时，`total_duration_s`、
`report_count`、`device_count` 和 `total` 均为 0，`items` 为空数组。

## 错误响应

- HTTP 401：缺少、格式错误或无效的 Admin Token。
- HTTP 422：请求字段校验失败；日期只提供一端；结束日期早于开始日期；日期跨度超过 31 天；或 `duration_s` 不是 1～3600 的整数。
- HTTP 429：SDK 写接口触发现有按 IP 写入限流。
- HTTP 500：服务端数据库写入失败。响应不返回内部异常详情。
