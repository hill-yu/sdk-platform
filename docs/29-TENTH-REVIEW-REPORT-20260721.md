# SDK 数据中台第十次代码审阅报告

> 审阅日期：2026-07-21  
> 审阅对象：`28-NINTH-REVIEW-FEEDBACK.md` 及提交 `3438fea` 至 `4eeaf6e` 后的代码  
> 审阅范围：路由级限流、状态回收、匿名采集威胁模型、事件拒绝语义、事务恢复和测试

## 1. 审阅结论

本轮确认以下修改已真实生效：限流改为 click/log 路由依赖，429 可由 FastAPI 正常处理；健康检查和读接口已豁免；`config_id` 已移到 commit 前缓存；全部 click 事件被拒绝时恢复非零业务码；新增了 3 项自动化测试。后端实测 **36 passed**，前端构建成功。

但 `28-NINTH-REVIEW-FEEDBACK.md` 声称“IP 字典内存无界增长已修复”不成立。当前清理器只删除已经为空的列表，却不会扫描并移除其他 IP 列表中的过期时间戳，因此历史 IP 键仍永久累积。本轮发现 **1 项必须修复、5 项建议修改**。

| 级别 | 数量 | 上线影响 |
|---|---:|---|
| 必须修复 | 1 | 长期运行时限流状态可无界增长 |
| 建议修改 | 5 | 威胁接受、响应语义和测试仍需完善 |
| 已确认修复 | 5 | 429、路由范围、ID 缓存、拒绝语义、基础测试 |

**最终判断：不能认定第九次审阅全部关闭。**

## 2. 必须修复

### 2.1 [必须修复] 定期清理没有删除其他 IP 的过期时间戳

**位置：** `backend/app/core/rate_limit.py:13-29`

每次请求只过滤当前 IP：

```python
self._store[ip] = [t for t in self._store[ip] if now - t < self.window]
```

每 1,000 次请求的全局清理却只查找空列表：

```python
expired = [ip for ip, times in self._store.items() if not times]
```

其他 IP 的列表从未经过时间过滤，即使其中所有时间戳早已过期，`times` 仍非空，因此不会被删除。

#### 实际探针

模拟时间 0 秒写入 1,000 个 IP，时间推进到 10 秒后再写入 1,000 个新 IP，已经跨过两次清理阈值：

```text
keys_after_two_cleanup_cycles = 2000
stale_first_key_timestamps = [0.0]
```

旧来源不仅键没有删除，过期时间戳也原样保留。

#### 修复建议

清理时必须按当前时间过滤每个键：

```python
for key, times in list(self._store.items()):
    active = [t for t in times if now - t < self.window]
    if active:
        self._store[key] = active
    else:
        del self._store[key]
```

同时设置最大键数量；达到上限时采用 TTL/LRU 淘汰。生产安全控制仍建议使用 Nginx `limit_req` 或 Redis 原子限流，而不是把无界 Python 字典作为唯一防线。

#### 必需测试

使用可控时钟写入超过 1,000 个不同 IP，推进时间超过窗口，再触发清理，断言旧键被删除、字典大小回落。测试还应覆盖清理后旧 IP 可重新请求。

## 3. 建议修改

### 3.1 [建议修改] 威胁模型不是正式风险接受记录

`THREAT-MODEL.md` 记录了匿名采集风险，但缺少风险所有者、批准人、接受日期、复审日期、量化阈值和应急处置。仅创建文档不能自动等于业务已接受风险。

建议增加：风险责任人、审批状态、到期复审时间、存储/费用上限、异常流量阈值、封禁与密钥升级触发条件。

### 3.2 [建议修改] “有效 app_id”描述与实现不符

威胁模型写“任何持有有效 app_id 的客户端均可写入”，但写入接口没有查询或校验 app_id 是否存在、启用或属于调用方。实际是任意字符串均可作为 app_id。

应修正文档，或至少增加 app_id 存在性/启用状态验证。即使匿名采集，也不应允许无限制造虚假租户标识污染分析维度。

### 3.3 [建议修改] 全部拒绝仍返回 HTTP 200

click 全部拒绝时业务码已恢复为 `4001`，但 HTTP 状态仍是 200。若这是既定 SDK 协议，应在 API 文档明确客户端必须检查业务码；否则建议返回 400/422，使网关和监控能识别失败。

log 路径的 `if not values` 在当前逻辑中没有任何拒绝条件，若 schema 保证至少一项日志，该分支基本不可达。建议删除误导分支或补明确的日志拒绝规则。

### 3.4 [建议修改] click/log 使用两个独立限流桶

两个模块分别创建 `write_limiter`，同一 IP 可在一秒内请求 click 10 次并请求 log 10 次，应用层合计允许 20 次。若目标是“写入接口合计 10 次/秒/IP”，应共享同一实例；若目标是每接口各 10 次，应在配置和文档中明确。

### 3.5 [建议修改] 自动化测试覆盖仍不完整

新增测试验证了 click 429、health 豁免和 click 全部拒绝，但尚未覆盖：

- IP 状态清理与容量上限；
- 时间窗口恢复；
- log 路由限流；
- 配置/版本读接口豁免；
- click/log 是否共享配额；
- DB execute 异常时 rollback 并返回 500；
- 多 worker/多实例行为。

## 4. 已确认修复

### 4.1 429 异常转换已修复

限流器现在作为路由 `Depends()` 执行，`HTTPException(429)` 位于 FastAPI 路由异常处理范围内。新增测试连续发送 11 次 click 请求并断言第 11 次为 429。

### 4.2 限流作用范围已修复

全局 middleware 已删除，只有 click/log 挂载限流依赖。`/health` 自动化测试连续 20 次均要求返回 200。

### 4.3 commit 前缓存 config_id 已修复

两个发布路径均在 `await db.commit()` 前执行 `config_id = config.id`，恢复路径不再依赖失败 commit 或 rollback 后的 ORM 对象状态。

### 4.4 全部 click 事件拒绝语义已改善

当没有可写入事件时返回 `code=4001`、`all_events_rejected`，不再伪装为 `code=0` 的部分成功。

### 4.5 基础自动化测试已增加

新增 `backend/tests/test_rate_limit.py`，使测试总数由 33 增至 36。28 号反馈中的 `XX passed in X.XXs` 是占位文本，不是可验证结果；本轮实测结果见下一节。

## 5. 验证记录

### 5.1 后端完整测试

```text
python -m pytest backend/tests -q
36 passed in 4.53s
```

### 5.2 前端生产构建

```text
npm run build
656 modules transformed
构建成功，主 JS 683.71 kB，gzip 237.20 kB
```

仍存在大于 500 kB 的 chunk 警告。

### 5.3 清理算法探针

```text
keys_after_two_cleanup_cycles = 2000
stale_first_key_timestamps = [0.0]
```

结论：跨过清理阈值后，已过期的历史 IP 仍未回收。

## 6. 下一轮最低验收条件

1. 全局清理真正过滤所有 IP 的过期时间戳并删除空键。
2. 增加最大容量或改用有界 TTL/Redis/Nginx 实现。
3. 补可控时钟的清理自动化测试。
4. 明确匿名采集风险的责任人、审批状态和复审期限，并纠正 app_id 描述。
5. 明确 click/log 配额是共享还是独立，并使代码、Nginx 和文档一致。
6. 后端完整测试保持 0 failed，前端构建保持成功。

