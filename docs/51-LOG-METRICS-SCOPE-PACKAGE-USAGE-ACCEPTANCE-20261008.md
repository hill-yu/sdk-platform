# 日志解析 scope、正式指标与使用时长验收记录

> 日期：2026-10-08（Asia/Shanghai）  
> 状态：代码终审通过；PG14.22 隔离回归通过；PG16 未验证  
> 范围：当前 worktree 的日志解析 scope、正式指标 UI、包画像、使用时长汇总与隔离数据库回归

## 1. 实施范围

本轮提交范围如下：

| Commit | 内容 |
|---|---|
| `53d78b8` | 统一日志分析 scope 校验 |
| `1110e3b` | 增加精确 latest parse scope 状态 |
| `2d4face` | 正式指标按 parse snapshot gating |
| `b5b133f` | 修复 parse scope/status race |
| `120d466` | 强化取消竞态与 true-zero 语义 |
| `1967c9e` | 移除旧 summary/details 主 UI；正式指标接入包画像；使用时长按最新设备聚合；新增隔离集成测试与设计文档 |
| `258cd18` | 更新页面滚动结构断言 |
| `e164d4d` | 修复 usage summary 非法 `device_model` 投影；固定 formal column mapping；强化 profile 生命周期 |
| `96c11d2` | 补齐 formal mapping 页面测试 mock |

未修改或未执行：SDK 上传协议、原始事件写入、配置、分区维护、旧 8102、生产 parse job、生产数据库、部署、合并、推送。

用户已有文件 `docs/50-LOG-METRICS-DEVICE-DURATION-H1-EXPORT-IMPLEMENTATION-20260930.md` 未暂存、未由本轮覆盖。

## 2. 需求对应

- 日志分析查询使用合法的北京时间边界转 UTC scope；latest job 按包名和完整半开区间精确匹配。
- 正式指标只在成功且 scope 匹配的 parse job 上展示，并使用 `snapshot_end_utc` 限制查询；旧正式结果不会跨 scope 泄漏。
- pending/running/failed/cancelled、无源数据、无 H1、全部 H1 失败和成功 H1 的真实零值分别展示；取消、轮询和迟到响应均有 generation guard。
- LogViewer 不再请求或渲染旧 log-analysis summary/details 主界面；旧 summary/details API 保持不变。
- formal column catalog 固定映射：
  - `alias/company/account` → 包画像字段；
  - `url` → 配置分布；
  - `expected_click_count` → 声明/计划卡片；
  - `actual_click_count` → 实际/响应卡片；
  - `ad_click_count` → 广告区域实际与目标表；
  - `interstitial_*` → 插屏指标卡片；
  - `parse_failure_count` → failed H1 卡片。
- `user_count`、`flow_count`、`average_duration_ms`、`success_rate` 等暂无正式组件映射的历史列不会伪装成正式指标；设置页会原样保留并标注“历史列，正式视图不展示”，未知 ID 可安全 round-trip。
- 包画像在合法查询、刷新和 parse 流程加载；reset/unmount、切包、迟到 GET 和迟到 save 不会污染当前包名。
- 使用时长汇总按 `(package_name, device_id)` 选 `server_ts DESC, id DESC` 的最新记录，再按包名聚合；同包多机型只返回一行，`device_model: null` 作为兼容字段。设备明细的机型过滤改为可选。

## 3. 测试证据

在当前 worktree 执行：

```text
backend: python -m pytest -q backend/tests
427 passed, 1 skipped in 10.70s
```

```text
frontend: npm test -- --run
31 passed (31)
188 passed (188)
```

```text
frontend: npm run build
✓ built in 5.21s
```

补充的真实数据库相关测试：

```text
python -m pytest -q backend/tests/test_log_scope_and_usage_integration.py backend/tests/test_usage_duration_summary.py backend/tests/test_usage_duration_admin_api.py
17 passed in 0.65s
```

`git diff --check` 通过。前端构建仅有既有 bundle size warning，无编译错误。

## 4. 隔离 PostgreSQL 证据

本机可用 PostgreSQL 工具版本：

```text
postgres (PostgreSQL) 14.22
initdb (PostgreSQL) 14.22
pg_ctl (PostgreSQL) 14.22
```

未启动既有 `C:\pgsql\data` cluster。为回归测试新建了独立 cluster：

- 数据目录：`C:\Users\喻远飞\AppData\Local\Temp\sdk-scope-pg14-a499aa5c`
- loopback：`127.0.0.1:55432`
- 专用数据库：`sdk_scope_test_a499aa5c`
- 专用测试 role：`sdk_test`

真实数据库测试通过：`17 passed in 0.65s`。测试 fixture 实际创建表并插入重叠 parse tasks、成功/失败 H1、true-zero H1、跨机型历史使用时长，然后执行真实 SQL 查询。

测试结束后执行：

```text
pg_ctl -D C:\Users\喻远飞\AppData\Local\Temp\sdk-scope-pg14-a499aa5c -m fast -w stop
waiting for server to shut down.... done
server stopped
pg_isready -h 127.0.0.1 -p 55432
127.0.0.1:55432 - no response
```

临时目录保留供复核；没有删除用户目录。当前仅证明 PostgreSQL 14.22 行为，PG16 尚未验证，后续是否提供 PG16 环境由用户单独决定。

## 5. 当前工作区与交付边界

终审后代码提交为 `96c11d2`，其父链包含上述 scope、parse snapshot、竞态、formal metrics、usage duration 和 acceptance changes。未创建 PR，未合并，未推送，未部署，未执行生产 parse job 或生产数据库操作。

当前工作区唯一未提交变更是用户已有的 `docs/50-LOG-METRICS-DEVICE-DURATION-H1-EXPORT-IMPLEMENTATION-20260930.md`，本轮保持原状。
