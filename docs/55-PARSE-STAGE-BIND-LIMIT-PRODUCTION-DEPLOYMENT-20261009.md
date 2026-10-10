# 解析暂存参数上限修复生产部署记录（2026-10-09）

## 发布版本

- 业务 SHA：`54b7c0f3991deb562a71a113c61d00971dc28c73`
- 生产 current：`/www/releases/sdk-platform/54b7c0f3991deb562a71a113c61d00971dc28c73`
- 旧回滚 release：`/www/releases/sdk-platform/7f4c233df33f28cb94ef2b669d187cc166800ae7`
- 远端 master 已快进至业务 SHA；未改数据库 schema、前端源代码或 8102。

## 发布前验证

- 本地全后端：`433 passed, 3 skipped`。
- 本地 PostgreSQL 14.22 UTF-8 专用库：集成测试连续两次 `1 passed`，事务回滚后用户表数量为 `0`。
- 生产 PostgreSQL 16 专用 loopback 库：

  ```text
  /www/releases/sdk-platform/current/backend/venv/bin/python -m pytest -q /tmp/sdk-parse-stage-54b7c0f/backend/tests/test_log_parse_stage_integration.py -m integration -rs
  1 passed, 1 warning in 15.36s
  ```

  专用数据库名为 `sdk_parse_stage_test_a54b`，专用角色和数据库由 trap 清理；清理后查询为空。未对 `sdk_platform` 建测试表。

## 备份

备份目录：`/root/sdk-deploy-backups/20261009_191700_54b7c0f`，权限 `root:root 700`。

- `sdk_platform.dump`：SHA256 `9886256f4695ae044e33d32eae9c270fcbad86b991769007bcef170998da73d9`
- `sdk_platform.restore-list`：217 行，SHA256 `083f1d0f47ad2607bce7deb67f81b4c77c7f363fe1b08f88e90cc5c425d59750`
- 旧 release archive：SHA256 `901f0aa8a2da33b409bedad20502e0c3640e949a7d4ad2c1fa25415f60015b10`
- current frontend dist archive：SHA256 `cc5a3539c4226f10c02356515a050b25f60530e7f69a2251b4ca8b4e8f0045d9`
- env snapshot：SHA256 `da1830abc833e2907e6ef7202540bc2eee19a6f8f413ea0e05f14a9afee76af9`

数据库使用 `pg_dump -Fc`，并立即执行 `pg_restore -l` 校验。备份包含四个 systemd unit 分目录、Nginx 配置、旧 release、current dist 和真实 env 快照。

## 切换与资产

- 新 release 使用 Git 精确 SHA 归档，无顶层目录；backend 复用已验证 venv symlink `/www/releases/sdk-platform/86a03f3f6b532ca3f7cf34485749b240a999e20c/backend/venv`。
- Nginx root 保持 `/www/releases/sdk-platform/current/frontend/dist`，新 release 仅复制原 current dist；JS/CSS/HTML SHA 与 docs53 保持：
  - JS `ac803a9a5efe59524da622d9ab1a95a646aab6d71225eebaad0952fab711d664`
  - CSS `1e835134433d13b6c9adb35d41b5a59e65321469ea7dbed38153b78d8662f3d1`
  - HTML `5dac514b2aeba38904bbc9fb389bad87e66956eab11d41a033de29c686df2e60`
- 原子切换 current 后重启 `sdk-api`、`sdk-admin`、`sdk-log-export-worker`、`sdk-log-parse-worker`；8102 保持原进程和端口。
- 8100/8101 在第 7 秒健康就绪；Nginx test/reload 成功。
- 四 unit 当前均 active/running、`NRestarts=0`、`ExecMainStatus=0`，cwd 均为 `current/backend`。

## 接口与日志

切换后直连 8100/8101 验证 health、usage summary、package profile、columns、coverage、log packages、configs、latest parse job 均 200；Nginx 正确 Host/SNI 路径另行按 `--resolve sdk.deeppopgame.xyz:443:127.0.0.1` 验证。部署窗口未见服务 error/exception/traceback；既有外部 usage 请求的 422 不属于本次变更。

## 生产解析验证

创建唯一任务：

- task id：`18`
- package：`com.ly.sixthshort`
- 北京时间范围：`2026-10-09 00:00–23:00`
- UTC 范围：`2026-10-08T16:00:00Z–2026-10-09T16:00:00Z`
- snapshot：创建时记录，`total_count=18031`
- 旧失败游标：`731315`

最终结果：

- 完成时间：北京时间 2026-10-09 19:39:59；耗时 `669s`
- 状态：`success`
- `processed_count/total_count`：`18031/18031`
- `h1_count`：`73262`
- `failed_h1_count`：`215`
- `no_h1_count`：`0`
- `decoded_count`：`0`（沿用现有任务字段行为，不作为本次成功判据）
- 最终 cursor event id：`751827`，已超过旧失败游标 `731315`
- `error_summary`：空
- 阶段表按固定摘要聚合：`<none>=73047`，`TimeoutError: H1 parse timed out=215`；未出现参数超限错误。
- 任务完成后仍无 pending/running 任务；服务和 Nginx health 持续 200。

本次只创建 task 18，没有重跑历史任务 14–17；不修改 timeout，215 条超时属于既有 1 秒超时行为。

## 回滚

如健康 deadline 或任务验证出现发布相关异常，将 current 原子恢复至旧 release，重启四个 unit 并重新验证 8100/8101；不回滚或修改数据库数据。未发生自动回滚。
