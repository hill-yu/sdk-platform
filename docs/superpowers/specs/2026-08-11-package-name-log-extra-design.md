# 事件包名统一与日志 Extra 字符串化设计

## 1. 目标

本次变更完成两项统一：

1. 全部当前运行事件链路将业务字段 `app_id` 统一改为 `package_name`；
2. 日志事件的 `extra` 改为必传字符串，`message` 改为可空。

不为旧 `app_id` 提供请求兼容别名。历史审阅报告保留历史原文，当前源码、数据库、前端、测试、初始化脚本、迁移脚本和现行接口文档统一使用 `package_name`。

## 2. SDK 请求协议

### 2.1 点击上报

```json
{
  "package_name": "com.example.app",
  "device_id": "device-001",
  "sdk_version": "1.2.0",
  "session_id": "session-001",
  "events": [
    {
      "type": "click",
      "page": "home",
      "element": "button",
      "extra": {"source": "banner"}
    }
  ]
}
```

点击事件只变更顶层包名字段。单条点击的 `extra` 继续为可选 JSON 对象。

### 2.2 日志上报

```json
{
  "package_name": "com.example.app",
  "device_id": "device-001",
  "sdk_version": "1.2.0",
  "logs": [
    {
      "level": "info",
      "message": "",
      "extra": "{ouoghaougoagahdgjalglauoi|dlaugouojlJ}"
    }
  ]
}
```

日志字段规则：

- `level` 必传，只允许 `debug`、`info`、`warn`、`error`，服务端转为小写；
- `extra` 必传且只能为 string；不要求是合法 JSON，不解析、不转换；
- `message` 可省略、为 `null` 或空字符串，服务端统一保存为空字符串；
- `tag` 和 `timestamp` 可选；
- 顶层 `device_id` 可选，未传时按 `null` 存储；
- 每批 1～100 条；
- 整体请求体仍受 SDK API 1 MB 限制。

对象、数组、数字、布尔值或 `null` 形式的日志 `extra` 均返回 422。缺少 `level` 或 `extra` 返回 422。

## 3. 包名规则

点击和日志顶层 `package_name`：

- 必传；
- 长度 1～255；
- 去除首尾空格并转换为小写；
- 使用配置接口相同的包名格式校验；
- 旧 `app_id` 不被识别，缺少 `package_name` 时返回 422。

## 4. 数据库存储

PostgreSQL 执行无损列重命名：

```text
sdk_events.app_id → sdk_events.package_name
```

同时：

- 列类型调整为 `VARCHAR(255)`；
- `idx_events_app` 替换为 `idx_events_package`；
- 所有事件分区保持原数据；
- 依赖字段的物化视图重建并输出 `package_name`；
- ORM `SdkEvent.app_id` 改为 `SdkEvent.package_name`。

日志 `payload.extra` 保存原始字符串；点击 `payload.extra` 继续保存 JSON 对象。JSONB payload 允许两种事件类型使用不同的内部字段类型。

## 5. Admin API 与前端

事件查询参数改为：

```http
GET /api/admin/events?package_name=com.example.app
```

事件列表项返回 `package_name`，不再返回 `app_id`。

Dashboard、事件筛选、前端字段绑定、表头、查询参数及统计 SQL 同步使用 `package_name`。物化视图的应用维度列同步重建。

## 6. 迁移设计

新增独立迁移脚本，默认只预检，正式执行要求显式 `--apply` 和确认串。迁移流程：

1. 检查 `sdk_events` 当前存在 `app_id` 还是 `package_name`；
2. 检查所有事件分区和物化视图依赖；
3. 记录迁移前事件总数及各分区数量；
4. 正式模式在事务和维护窗口内重命名列、扩大长度、替换索引；
5. 重建 `mv_daily_event_stats`，使其输出 `package_name`；
6. 重建依赖索引和刷新函数需要的对象；
7. 验证事件总数、分区数量和非空包名数量迁移前后一致；
8. 再次运行时识别已迁移结构并安全退出。

生产执行前必须完成 PostgreSQL 完整备份并停止 SDK API 与 Admin API 写入。任一步失败则事务回滚。

## 7. 错误和兼容语义

- 旧请求只传 `app_id`：422；
- `package_name` 格式错误：422；
- 日志缺少 `level`：422；
- 日志缺少 `extra`：422；
- 日志 `extra` 不是字符串：422；
- 日志 `message` 缺失、`null` 或空字符串：接受并保存为空字符串；
- 数据库写入失败：500，事务回滚；
- 点击与日志限流保持每 IP 每秒 10 次。

## 8. 范围约束

- 不修改配置管理中的 `package_name` 语义；
- 不修改 SDK 版本管理；
- 不把点击事件 `extra` 改成字符串；
- 不解析日志 `extra` 内容；
- 不批量改写历史审阅报告；
- 不保留 `app_id` 请求别名。

## 9. 测试与验收

必须测试：

1. 点击使用规范化后的 `package_name` 写入；
2. 点击只传 `app_id` 返回 422；
3. 日志 `level` 和字符串 `extra` 写入成功；
4. 日志字符串 `extra` 原样进入 payload；
5. 日志缺少 `level` 或 `extra` 返回 422；
6. 日志 `extra` 为对象、数组、数字、布尔值或 null 时返回 422；
7. 日志 `message` 缺失、null、空字符串均保存为空字符串；
8. Admin 按 `package_name` 查询事件；
9. Admin 事件响应只含 `package_name`，不含 `app_id`；
10. Dashboard 和物化视图使用 `package_name`；
11. 数据库迁移保留全部历史事件和分区数据；
12. 迁移重复执行安全退出；
13. 当前运行源码和现行文档不存在业务字段 `app_id`；
14. 后端全量测试通过；
15. 前端测试与构建通过；
16. 本地服务重启后完成点击、日志、Admin 查询冒烟验证。
