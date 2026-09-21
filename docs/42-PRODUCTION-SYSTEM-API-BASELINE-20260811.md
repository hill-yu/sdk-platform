# 生产系统 API 基线

## 日志分析接口

### 包资料部分更新

```http
PUT /api/admin/package-profiles/{package_name}
```

请求体至少包含 `alias`、`company`、`account` 中的一个字段。接口只更新请求中实际提交的字段；省略字段保持原值。显式提交空字符串表示清空该字段。未知字段被拒绝。

### 重解析任务

```http
POST /api/admin/log-analysis/reparse
```

接口创建有界异步任务。任务保存全部筛选条件，由 admin 后台 worker 按批执行。任务状态为：`pending`、`running`、`success`、`failed`、`cancelled`。

重解析筛选条件包括北京时间自然日范围、精确包名、现有解析状态和三段整数解析器版本上限。任务不保存原始日志内容；批处理复用现有日志解码与投影逻辑。

`sdk_log_reparse_jobs` 使用 `lease_owner VARCHAR(64)` 和
`lease_expires_at TIMESTAMPTZ` 实现多实例租约。worker ID 在 worker 进程内稳定；领取时在
`FOR UPDATE SKIP LOCKED` 下选择 `pending` 或已过期的 `running` 任务，写入 10 分钟租约，且不重置已有游标。
批处理、续租以及 `success`/`failed` 状态推进都必须带当前 owner 条件；租约失效的旧 owner 不得推进游标、计数或覆盖终态。

旧状态约束迁移顺序固定为：删除旧约束，先将历史 `succeeded` 更新为 `success`，再添加
`pending/running/success/failed/cancelled` 目标约束。重复 dry-run 不应再次生成这些变更。

## 管理端原始事件接口

### 事件筛选选项

```http
GET /api/admin/events/filter-options
```

可选查询参数为 `package_name`。响应使用 `code=0` 包装，`data` 包含
`package_names` 和 `sdk_versions` 两个数组。两个数组均按数据库值去重、升序排列；传入
`package_name` 时，`sdk_versions` 只包含该包名的日志版本。选项仅来自 `event_type = log`
的事件，空包名、空版本和空结果不会伪造默认值。

### 事件列表

```http
GET /api/admin/events
```

新增可选查询参数 `sdk_version`，按 `sdk_events.sdk_version` 精确匹配。事件类型、日志级别、
包名、设备 ID、北京时间自然日范围、排序、分页及响应字段保持原有语义；多个筛选条件使用
`AND` 组合。
