# 对 20-FIFTH-REVIEW-REPORT-20260716.md 的分析反馈

> 日期：2026-07-16 | 分析人：汉堡包 🍔

---

## 总体评价

审阅人通过 ASGI 消息级别的探针（逐个检查 `http.response.start`/`http.response.body` 的数量和内容），发现 3.1 虽然返回 413 状态码，但响应体是两个 JSON 拼接——这对 HTTP 客户端来说是破坏性的。

3.2 是我前几轮的盲区：我一直以为 `config.cos_upload_status = 'failed'` 会持久化，但忽略了后面的 `rollback` 会把内存修改抹掉。审阅人的 Outbox 建议是正确方向。

3.3 对账读版本化 URL 而非 latest.json，这让对账完全失去了意义。

---

## 逐条修复记录

### 3.1 [必须修复] 双响应体 → ✅ 已修复

**根因**：V2 方案在 receive 检测超限 + send 拦截，`exceeded=False` 后下游 body 被透传。

**中间件演进**：
| 版本 | 方案 | 结果 |
|------|------|------|
| V1 | BaseHTTPMiddleware + exception | 双体 bug |
| V2 | 纯 ASGI + send 拦截 | 双体 bug（exceeded flag 时序问题） |
| V3 | **先缓冲全部 body，再调用 app** | 协议干净 ✅ |

**V3 核心逻辑**：
1. 缓冲全部 body chunk，累计字节
2. 超限 → 直接发 413，return（**不调用 app**）
3. 未超限 → 重放 body 给 app

**Commit**: `7d552ae`

### 3.2 [必须修复] commit 失败补偿不持久化 → ✅ 已修复

**根因**：`cos_upload_status='failed'` 写在同一事务内，被后续 rollback 抹掉。

**修复**：commit 失败后，用**独立 session + 独立事务**写入 failed 状态：
```python
from app.core.database import async_session_factory
async with async_session_factory() as recovery_session:
    async with recovery_session.begin():
        cfg = await recovery_session.get(SdkConfig, config.id)
        cfg.cos_upload_status = "failed"
```

**Commit**: `c8f8739`

### 3.3 [必须修复] 对账读版本化 URL → ✅ 已修复

**根因**：`published.cdn_url` 是版本化对象的 URL（`config/v2026...json`），不是 latest.json。

**修复**：对账时构造 `{CDN_BASE_URL}/config/latest.json`，带缓存穿透参数（`?_t={timestamp}`）。

**Commit**: `7e56ce3`

### 4.1 rollback 重复锁 → ✅ 已修复
内部函数加注释"调用方已持锁"，去重。
**Commit**: `1cbc1aa`

### 4.x 测试 + 技术债 → ✅ 已修复
新增 3 项测试（对账 latest 一致性 + commit 失败持久化）。技术债记录更新。
**Commit**: `aca8b10` + `c94109a`

---

## 测试结果

```
33 passed in 8.56s ✅（旧 30 + 新增 3）
```

## 提交记录

```
c94109a docs: 更新技术债，明确对账定时任务和Outbox模式
aca8b10 test: 4.x 增加对账latest一致性测试+commit失败持久化测试
7e56ce3 fix: 3.3 对账改为读取latest.json，带缓存穿透
1cbc1aa fix: 4.1 rollback去重advisory lock获取
c8f8739 fix: 3.2 commit失败用独立session持久化failed状态
7d552ae fix: 3.1 中间件改为先缓冲再调用app，消除双响应体
```

---

## 五轮审阅全景

```
第一次: 13 项关闭 → 17 passed
第二次:  7 项关闭 → 17 passed
第三次:  6 项关闭 → 27 passed
第四次:  6 项关闭 → 30 passed
第五次:  6 项关闭 → 33 passed
─────────────────────────
总计:   38 项 → 0 剩余
测试:   33 passed, 0 failed
提交:   56 次 commit
```

### 文档索引

| 审阅报告 | 反馈文档 |
|----------|---------|
| `12-CODE-REVIEW-REPORT-20260716.md` | `13-REVIEW-FEEDBACK.md` |
| `14-SECOND-REVIEW-REPORT-20260716.md` | `15-SECOND-REVIEW-FEEDBACK.md` |
| `16-THIRD-REVIEW-REPORT-20260716.md` | `17-THIRD-REVIEW-FEEDBACK.md` |
| `18-FOURTH-REVIEW-REPORT-20260716.md` | `19-FOURTH-REVIEW-FEEDBACK.md` |
| `20-FIFTH-REVIEW-REPORT-20260716.md` | `21-FIFTH-REVIEW-FEEDBACK.md` |

---

> 🍔 第五次审阅全部关闭。33 passed, 0 failed。
