# SDK 数据中台第八次扩展审阅报告

> 日期：2026-07-16  
> 基线：提交 `8c5c20c`（代码未发生新变化）  
> 范围：在第七次复审基础上，扩展检查数据库会话、SDK 写入接口、鉴权与运行边界

## 1. 结论

由于 `23-SIXTH-REVIEW-FEEDBACK.md` 及代码没有新提交，第七次报告中的 1 项必须修复仍然存在。本轮扩展检查另外发现 2 项必须修复风险和 3 项建议修改风险。

| 级别 | 数量 | 结论 |
|---|---:|---|
| 必须修复 | 3 | 不建议按“全部关闭”状态上线 |
| 建议修改 | 3 | 上线前应落实或形成明确控制措施 |

## 2. 必须修复

### 2.1 rollback 后读取过期 ORM 对象

`config_service.py:112` 和 `:184` 执行 rollback 后，仍在 `:118/:122/:124`、`:190/:194/:196` 读取 `config.id`。rollback 会 expire ORM 属性，AsyncSession 下可能触发 `MissingGreenlet`，使补偿事务失败。

修复方式：rollback 前保存 `config_id = config.id`，后续只使用不可变局部变量；并用真实 AsyncSession 验证。

### 2.2 SDK 批量写入捕获数据库异常后继续使用失败事务

`backend/app/api/sdk/click.py:64-73` 和 `log.py:59-68` 捕获 `db.execute()` 异常后只修改计数并返回业务 JSON，没有 rollback，也没有重新抛出异常。

但 `get_db()` 会在接口返回后继续执行 `await session.commit()`。PostgreSQL 事务在 SQL 失败后通常处于 aborted 状态，随后 commit/依赖清理会再次失败。结果是：

- handler 构造的 `code=5001` 响应不一定能稳定发送；
- 实际行为取决于 FastAPI dependency teardown；
- 日志会出现同一故障的二次异常；
- 当前测试 fake 不模拟 PostgreSQL aborted transaction。

应选择一种清晰语义：数据库错误直接抛 HTTP 5xx，让 `get_db()` rollback；或在 handler 内显式 rollback，并确保依赖层不会再次 commit。不要吞掉异常后把失败 session 交还给自动 commit 依赖。

### 2.3 公网 SDK 写入接口缺少任何滥用控制

`/api/v1/click` 和 `/api/v1/log` 无鉴权、签名、限流或 app_id 有效性校验。请求体大小限制只能限制单请求内存，不能阻止攻击者持续提交合法大小批次写满事件表、连接池和日志存储。

若这些接口面向公网，至少应具备：

- app_id/API key 或带时间戳签名；
- 按 app_id 和来源 IP 的速率限制；
- 单 app 配额与异常流量告警；
- 反向代理层连接数、请求速率和超时限制。

若设计上依赖网关完成，必须在部署清单和配置中提供可验证规则，不能只作为口头假设。

## 3. 建议修改

### 3.1 失败仍返回 HTTP 200

SDK 全部写入失败时返回业务码 `5001`，但 HTTP 状态仍为 200。网关、APM 和客户端默认重试策略可能把它视为成功。建议为服务端写入故障返回 5xx；数据校验导致的全部拒绝返回 4xx，并保留业务码作为补充。

### 3.2 recovery 结果与响应描述不一致

恢复记录不存在或 recovery transaction 失败时，API 仍返回“系统已记录”。应区分恢复成功、记录不存在、恢复失败，并只在真实提交后输出成功日志。

### 3.3 缺少真实 PostgreSQL 故障测试

现有 fake 不覆盖 transaction aborted、rollback expire、advisory lock 和独立事务 commit。`TECH-DEBT.md` 已记录该缺口，但它直接覆盖当前发布补偿和事件上报的关键失败语义，建议提升优先级。

## 4. 已确认项

- Admin 路由统一使用 Bearer Token，并通过 `hmac.compare_digest` 比较。
- Admin 启动时会拒绝空、过短和明显占位 Token。
- SDK/Admin 请求体限制已共用同一中间件。
- disconnect 与累计超限路径已正确提前终止。
- SQL 文本中的业务参数均通过绑定参数或 SQLAlchemy 表达式传递，当前未发现直接字符串拼接 SQL 注入。

## 5. 验证基线

沿用同一未变化代码快照的最新验证：

```text
python -m pytest backend/tests -q
33 passed in 8.52s

npm run build
构建成功，656 modules transformed
主 JS 683.71 kB（gzip 237.20 kB），存在 >500 kB chunk 警告
```

## 6. 下一轮最低验收条件

1. rollback 前缓存 ORM 标识，不在 rollback 后读取原实例。
2. SDK 写入失败不再吞异常后触发依赖层 commit。
3. 明确并验证公网写入接口的鉴权/签名、限流和配额控制。
4. 使用真实 PostgreSQL 覆盖 commit 失败、transaction aborted、锁释放和独立补偿提交。
5. 后端完整测试保持 0 failed，前端构建成功。

