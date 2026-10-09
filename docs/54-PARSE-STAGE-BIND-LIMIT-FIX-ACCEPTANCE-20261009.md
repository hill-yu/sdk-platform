# 解析暂存批量参数上限修复验收记录（2026-10-09）

## 根因

生产 `sdk-log-parse-worker` 使用 SQLAlchemy 多行 `INSERT ... VALUES` 写入展开后的 Click 暂存记录。asyncpg 单条语句最多接受 32,767 个绑定参数；生产任务 17 下一批为 3,036 条 Click × 17 字段 = 51,612 参数，任务 14 首批为 3,590 × 17 = 61,030，触发 `InterfaceError`。

修复将 H1/Click 暂存写入按字段数切分，每段最多 30,000 参数且最多 1,000 行；不改变原始事件读取批次、解析口径、游标推进或 commit 边界。

## 变更

- `backend/app/services/log_parse_job_service.py`：新增 `_insert_stage_rows_in_chunks`，空列表、单行、整块、余块和异字段集合均有测试；异字段直接拒绝，避免 SQLAlchemy 静默丢字段。
- `backend/app/workers/log_parse_worker.py`：失败日志仅记录 job_id、异常类型链、合法 SQLSTATE 和文件/行/函数栈帧；不输出异常消息、SQL、bind 参数或 payload，并限制异常链深度且防循环。
- 未修改数据库 schema、前端、协议、七桶业务或 publish SQL。

## 验证证据

### TDD 与测试

1. 修复前红测：3 failed（helper 不存在、worker 无安全日志）。
2. 定向测试：`python -m pytest -q backend/tests/test_log_parse_job_service_v2.py backend/tests/test_log_parse_worker.py` → `40 passed`。
3. 全后端测试：`python -m pytest -q backend/tests -rs` → `433 passed, 3 skipped`。
4. 跳过原因：
   - `SDK_LOG_SCOPE_TEST_DATABASE_URL` 未设置，真实 PostgreSQL scope 回归跳过。
   - `SDK_PARTITION_TEST_DATABASE_URL` 未设置，分区维护回归跳过。
   - `SDK_PARSE_STAGE_TEST_DATABASE_URL` 未设置时，新增解析暂存 PostgreSQL 回归默认跳过。

### 隔离 PostgreSQL 回归

测试文件：`backend/tests/test_log_parse_stage_integration.py`。

默认跳过；仅当 `SDK_PARSE_STAGE_TEST_DATABASE_URL` 指向 loopback 且数据库名严格匹配 `sdk_parse_stage_test_[0-9a-f]{4,32}` 的专用测试库时运行，明确拒绝 `sdk_platform`、`postgres` 和 template 数据库。测试使用事务内 `Base.metadata.create_all`，不调用 `drop_all` 或全表 DELETE，外层事务结束后回滚，不连接生产库。

本次手工验收环境：PostgreSQL 14.22（Windows，UTF-8，loopback 临时集群，端口 55432）。执行的核心命令：

```powershell
$env:PYTHONPATH='backend'
$env:SDK_PARSE_STAGE_TEST_DATABASE_URL='postgresql+asyncpg://postgres@127.0.0.1:55432/sdk_parse_stage_test_ab12'
python -m pytest -q backend/tests/test_log_parse_stage_integration.py -m integration
```

实际验证结果（连续运行两次，均 `1 passed in 2.1s`）：

- 1,833 条 H1 和 3,590 条 Click 暂存记录实际分段写入成功。
- 注入第二个 Click chunk 失败后，旧 H1/Click 暂存行仍保留。
- `processed_count`、`h1_count`、cursor、lease、heartbeat 均保持原值。
- 整批事务回滚，无部分写入。
- 两次运行后查询专用库用户表数量为 `0`，证明外层事务显式 rollback 且无残留 DDL/数据。

生产 PostgreSQL 16 尚未执行该测试；生产任务未重跑，服务未重启，未部署本提交。
