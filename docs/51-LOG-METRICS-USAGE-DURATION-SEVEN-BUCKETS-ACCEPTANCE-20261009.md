# 使用时长七桶与每桶总时长验收记录（2026-10-09）

## 范围与基线

本次只细化 Admin 使用时长汇总 `buckets`，不改变上传协议、日志解析、配置、数据库 schema、31 日限制或 UTC+8 口径；未合并 master、未推送、未部署、未连接生产。

- BASE：`04c7e8a2b751ba1934249afd2564db0211f3826d`
- 实现 HEAD（本文档提交前）：`3ca728e48753b83c320e6e109479d21d1a25833f`
- 分支：`codex/usage-duration-seven-buckets-20261009`
- 规格：`docs/superpowers/specs/2026-10-09-usage-duration-seven-buckets.md`
- 计划：`docs/superpowers/plans/2026-10-09-usage-duration-seven-buckets.md`

## API 与 SQL 契约

`buckets` 固定按以下顺序返回：

```text
le_120, 121_300, 301_600, 601_899, 900_1199, 1200_1499, ge_1500
```

每桶字段为 `key`、`count`、`share`、`total_duration_s`。同一 `(package_name, device_id)` 在所选范围内由 `server_ts DESC, id DESC` 选最新记录，再由同一包级 SQL 聚合得到桶数据；不按 `device_model` 分组，不汇总历史，不由前端下载全量设备重算。

已验证以下不变量：

- `sum(bucket.count) == device_count`
- `sum(bucket.total_duration_s) == package total_duration_s`
- 有设备时空桶为 count/share/total 全 0
- 无设备时沿用原有无行/null 语义
- 边界覆盖 `1/120/121/300/301/600/601/899/900/1199/1200/1499/1500/3600`
- 多历史记录、同 timestamp 的较大 id 胜出、多包、跨机型同设备去重均覆盖

前端保持包总时长、平均时长、最后上报、筛选和按需设备明细；七个桶单元格显示设备数（占比）及 `formatDuration` 格式的桶总秒数，表格保留内部横向滚动，不新增 21 个独立列。

## Red-green 证据

先提交失败测试后实现：

- 后端红灯：`2 failed, 6 passed, 1 skipped`；失败点为旧四桶响应缺少七桶总时长和七桶 SQL 聚合
- 后端相关绿灯：`44 passed`
- PG 集成绿灯：`1 passed in 0.62s`
- 前端七桶/API 定向绿灯：`2 test files, 7 passed`

全量验证：

- 后端：`428 passed, 1 skipped in 11.11s`
- 前端：`31 passed (31)`, `188 passed (188)`
- 构建：`vue-tsc --noEmit && vite build` 成功，`708 modules transformed`，`built in 4.75s`
- `git diff --check`：无输出

全量前端首次运行时有 3 个既有 `LogViewer` 日期相关测试失败：测试 hardcode 了 2026-10-06 至 08，而当前日期已 rollover 到 2026-10-09，组件按当前日期生成 07 至 09，mock job 被合法 scope 校验丢弃。仅为这组测试显式设置日期输入，未修改业务逻辑；修正后 `LogViewer.test.ts` 为 `36 passed (36)`，全量前端恢复 `188 passed`。

## 真实 PostgreSQL 验证

- 本机版本：PostgreSQL 14.22
- 临时 cluster：loopback `127.0.0.1:55432`
- 集成数据库：专用 `sdk_scope_test_7b0c2026`
- 测试使用真实 SQL 建表、插入边界数据并查询汇总；测试库已删除，cluster 已停止
- 未启动未知库、未安装大型工具、未连接生产

## 变更提交

```text
7ee85f6 docs: plan seven usage duration buckets
a36050a test: specify seven usage duration buckets
27e6ffa feat: add seven usage duration bucket totals
3ca728e test: stabilize date-scoped parse viewer tests
```

本文档是验收记录提交；该 docs-only 提交不会改变上述实现代码或触发任何生产操作。
