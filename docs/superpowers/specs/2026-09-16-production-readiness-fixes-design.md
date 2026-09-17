# 日志分析生产就绪修复设计

## 1. 目标与范围

在 `codex/utc8-log-analysis` 已合并批量日志导出的基础上，仅修复发布审查确认的三项问题：

1. 24 小时趋势物化视图返回无时区时间，序列化时可能触发 500；
2. 包资料单字段保存会把其他字段清空；
3. 重解析接口只创建任务，没有消费者执行，且任务筛选条件和完成状态不一致。

不调整现有日志解析口径、导出格式、配置管理、鉴权协议或页面视觉结构。

## 2. 24 小时趋势时间语义

### 设计

PostgreSQL 16 使用三参数形式：

```sql
date_trunc('hour', server_ts, 'Asia/Shanghai') AS hour
```

输入和输出均为 `TIMESTAMPTZ`，分桶边界按北京时间计算，但数据库仍保存绝对时间。API 继续通过 `serialize_business_time()` 输出显式 `+08:00`。

迁移程序读取 `mv_hourly_trend.hour` 的实际列类型；当不是 `timestamp with time zone` 时重建小时物化视图和唯一索引。迁移前后继续校验事件总数、非空 `extra` 数和各分区行数。

### 验证

- SQL 结构测试必须断言使用三参数 `date_trunc`；
- 服务测试使用 PostgreSQL 实际会返回的 aware datetime；
- 迁移测试覆盖旧 `timestamp without time zone` 到新类型的重建计划；
- 生产 smoke 断言 24h 趋势返回 200，且每个时间字符串带 `+08:00`。

## 3. 包资料部分更新

### 设计

保留现有 `PUT /api/admin/package-profiles/{package_name}` URL，修改请求语义为“只更新请求中出现的字段”：

```json
{ "alias": "新别名" }
```

Pydantic 字段默认值改为 `None`，路由使用 `payload.model_fields_set` 取得实际提交字段。服务层接收 `updates: dict[str, str | None]`，仅把这些列写入 PostgreSQL `ON CONFLICT DO UPDATE`；首次创建时未提交列保持 NULL。显式空字符串仍表示清空该字段。

响应通过一次数据库读取返回完整包资料，避免前端误以为未提交字段为空。前端现有单字段 payload 保持不变。

### 验证

- 更新 alias 后 company/account 保持原值；
- 显式 `{ "alias": "" }` 可以清空 alias；
- 空对象返回 422，未知字段继续被拒绝；
- 前端组件继续只发送当前编辑字段。

## 4. 重解析任务闭环

### 持久化

`sdk_log_reparse_jobs` 增加：

- `status_filter VARCHAR(32)`：创建任务时的日志解析状态筛选；
- `decoder_version_before VARCHAR(32)`：创建任务时的解析器版本筛选。

任务状态统一为：`pending`、`running`、`success`、`failed`、`cancelled`。迁移必须先删除旧约束，再把历史 `succeeded` 改为 `success`，最后添加目标约束，保证已有数据可迁移。
表同时增加 `lease_owner VARCHAR(64)` 和 `lease_expires_at TIMESTAMPTZ`，用于多实例安全租约。

### 执行模型

新增专用 `log_reparse_service`：

1. 用 `FOR UPDATE SKIP LOCKED` 领取一个 pending 或租约已过期的 running 任务并置为 running；worker ID 在进程内稳定，领取时写入 owner 和 10 分钟 expiry，保留已有游标；
2. 按 `(server_ts, id)` 稳定游标读取最多 50 条符合范围、包名、状态和解析器版本的日志事件；
3. 对每条事件调用现有 `build_decoded_values()` 和 `upsert_decoded_values()`，先删除该事件旧解析结果再写入新结果；
4. 每批更新游标和累计计数并提交，避免长事务；
5. 每批处理和续租都校验当前 owner；无更多记录时仅由当前 owner 清租约并置为 success；异常时仅由当前 owner 写入脱敏且限长的 `error_summary`、清租约并置为 failed；租约失效的旧 owner 不得推进游标、计数或覆盖任务；
6. 不复制、不记录原始 `extra`，只从现有 `sdk_events.payload` 读取。

Admin API lifespan 启动独立重解析循环；取消服务时与 ETL、在线解析循环一起有序退出。单实例和多实例都依赖行锁避免重复领取。

### 筛选语义

- 日期范围使用北京时间自然日转换后的 UTC 半开区间；
- `package_name` 完全匹配；
- `status_filter` 匹配该事件现有解析结果状态；
- `decoder_version_before` 使用三段整数比较，不使用字符串字典序；
- 创建任务时至少有一个范围或筛选条件，继续拒绝无条件全表重解析。

### 验证

- 创建任务完整持久化两个筛选字段；
- worker 领取、批处理、游标推进、计数、成功和失败状态都有单元测试；
- 两个 worker 并发领取时 SQL 包含 `SKIP LOCKED`；
- lifespan 启动并取消第三个后台任务；
- 状态约束在初始化 SQL、ORM 和迁移中完全一致。

## 5. 兼容性与回滚

- API URL 不变；包资料请求从“全量覆盖”收紧为“部分更新”，与现有前端实际调用一致；
- 重解析请求结构不变，只修复此前未落库、未执行的问题；
- 小时趋势响应结构不变，只修复时间类型；
- 数据库迁移只新增可空列、替换状态约束、重建物化视图，不修改原始事件表和原始日志；
- 回滚时恢复部署前数据库备份和应用版本备份，不对生产库执行逆向猜测式 DDL。

## 6. 发布门禁

1. 后端全量测试、前端全量测试和前端构建通过；
2. 当前窗口完成独立 diff 审查，不存在 Critical/Important；
3. 服务器只读核对当前版本、服务、路径、数据库规模和磁盘空间；
4. 生成带时间戳的 PostgreSQL custom-format 备份并用 `pg_restore --list` 校验；
5. 生成应用目录、前端产物、环境配置和 systemd 单元备份，记录 SHA-256；
6. 对生产数据库先运行迁移 dry-run，核对计划后才 apply；
7. 部署准确 Git commit，重启服务并检查日志；
8. 健康、鉴权、24h 趋势、包资料部分更新、重解析小范围任务、日志查询和批量导出 smoke 全部通过；
9. 任一门禁失败立即停止投入生产并按备份回滚。
