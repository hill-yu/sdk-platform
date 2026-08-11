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
GET /api/admin/events?package_name=com.example.app
Authorization: Bearer <ADMIN_TOKEN>
```

响应事件项返回 `package_name`，不再返回 `app_id`。前端事件明细筛选也传 `package_name`。

## 5. 数据库升级

先停止 SDK 写入或进入维护窗口，备份后执行：

```bash
python scripts/migrate_event_package_name.py
python scripts/migrate_event_package_name.py --apply --confirm MIGRATE_EVENT_PACKAGE_NAME
```

第一条只生成预检计划，不写数据库。第二条在单个事务内完成列改名、字段扩容、索引和物化视图重建，并校验事件总数、主表、分区表与视图列。已迁移数据库重复执行时不会再修改结构。
