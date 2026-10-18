# 日志历史与配置发布验收记录

## 代码状态

- Worktree：`C:\Users\喻远飞\.codex\worktrees\log-history-publish-safety-20261018\SDK`
- 分支：`codex/log-history-publish-safety-20261018`
- 最终提交（本记录提交前）：`be55050cef6ee909da8e7528a1aec5e5f868dfb`
- 该记录补充提交后以 `git rev-parse HEAD` 为准。
- 生产环境未写入、未重启、未部署、未合并或推送。

## 可复跑 PostgreSQL 验收

测试文件：

- `backend/tests/test_log_history_postgres_integration.py`
- `backend/tests/test_config_publish_postgres_integration.py`

两者都要求专用数据库名白名单，避免误连生产：

```powershell
$env:SDK_LOG_HISTORY_TEST_DATABASE_URL = "postgresql+asyncpg://.../sdk_log_history_test_<id>"
python -m pytest backend/tests/test_log_history_postgres_integration.py -q -rs

$env:SDK_CONFIG_PUBLISH_TEST_DATABASE_URL = "postgresql+asyncpg://.../sdk_config_publish_test_<id>"
python -m pytest backend/tests/test_config_publish_postgres_integration.py -q -rs
```

本次使用临时 PostgreSQL 14 实例 `127.0.0.1:55432`：

- `test_log_history_postgres_integration.py`：1 passed。
- 任务 A/B 使用同包同范围、不同 `job_id` 和不同 click 结果；overview、configs、targets、failures、H1+click 全部按 job 隔离。实际 SQL 中没有正式 H1/click 表引用，stage 表和 `job_id` 绑定均存在。
- `test_config_publish_postgres_integration.py`：1 passed。
- 两个真实异步会话中，保存会话持有草稿行锁；发布会话等待锁释放后用旧 `expected_updated_at` 得到冲突，状态仍为 draft、版本未递增、COS 状态仍为 pending。
- 临时实例已停止；临时目录因执行策略禁止递归删除而保留在 `%TEMP%`，不含生产数据。

## 自动化验证

```powershell
cd frontend
<bundled-node> ...\vitest.mjs run --pool=threads --poolOptions.threads.singleThread=true
```

- 前端最终全量：41 files / 227 tests passed。
- `vue-tsc --noEmit`：passed。
- `vite build`：passed；仅有既有的 bundle 大小提示。

```powershell
python -m pytest backend/tests -q -rs --disable-warnings
```

- 后端：453 passed，3 skipped。
- 跳过原因：`SDK_PARSE_STAGE_TEST_DATABASE_URL` 未设置、`SDK_LOG_SCOPE_TEST_DATABASE_URL` 未设置、`SDK_PARTITION_TEST_DATABASE_URL` 未设置；均为专用真实数据库集成测试，不是失败。
- 仓库根目录 `python -m pytest` 还会收集 `backend/test_api2.py`，该文件在收集阶段直接访问未启动的本地 API 并因连接拒绝失败；它不是 `backend/tests` 标准套件的一部分，本次未启动该外部依赖来掩盖问题。

## 浏览器验收待记录

本地前后端需要在当前机器提供专用数据库与私密配置后启动；浏览器验收必须确认桌面与 390px 下包名下拉、历史折叠/展开、使用时长状态、发布预览取消/确认和受保护 API 不回显凭据。未具备这些启动条件前，不把浏览器结果写成已通过。
