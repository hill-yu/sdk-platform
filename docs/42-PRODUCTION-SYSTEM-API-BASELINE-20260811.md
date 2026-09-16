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
