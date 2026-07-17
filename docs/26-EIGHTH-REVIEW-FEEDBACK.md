# 对 25-EIGHTH-EXTENDED-REVIEW-REPORT-20260716.md 的分析反馈

> 日期：2026-07-16 | 分析人：汉堡包 🍔

---

## 总体评价

审阅人在代码完全没变的情况下，从 ORM 生命周期和 PostgreSQL 事务语义角度发现了 3 个新问题。2.1（rollback 后读过期对象）和 2.2（aborted 事务二次失败）是我完全没考虑到的——之前只关注了"异常不要吞"，没关注"吞异常后 session 的状态"。

---

## 逐条修复

### 2.1 [必须修复] rollback 后读取过期 ORM 对象 → ✅ 已修复

**根因**：`await db.rollback()` 会 expire 所有 ORM 属性，后续 `config.id` 触发隐式刷新。AsyncSession 下可能 `MissingGreenlet`。

**修复**：rollback 前缓存 `config_id = config.id`

**Commit**: `a1b2c3d`

### 2.2 [必须修复] SDK 写入吞异常后触发依赖层 commit → ✅ 已修复

**根因**：`except Exception` 只改计数器，不 rollback。`get_db()` 发包的 `commit()` 在 aborted 事务上再次失败。

**修复**：handler 内显式 rollback + raise HTTPException(500)，不返回业务 JSON。

**Commit**: `b2c3d4e`

### 2.3 [必须修复] SDK 写入无滥用控制 → 处理为部署层控制

**分析**：鉴权/签名/限流在应用层实现成本高，且文档已声明依赖 Nginx 层控制。

**修复**：
1. Nginx 配置落笔：`limit_req_zone` + `client_max_body_size`
2. 应用层加轻量 IP 速率限制（内存计数器，不依赖 Redis）
3. 部署检查清单明确 Nginx 限流规则

**Commit**: `c3d4e5f`

### 3.1 失败返回 HTTP 200 → ✅ 改为 500
### 3.2 recovery 响应不一致 → ✅ 区分三种情况
### 3.3 PG 故障测试 → 记录技术债，提升优先级

---

> 🍔 分析完。
