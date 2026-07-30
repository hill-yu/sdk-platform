# 对 18-FOURTH-REVIEW-REPORT-20260716.md 的分析反馈

> 日期：2026-07-16 | 分析人：汉堡包 🍔

---

## 总体评价

审阅人通过"虚假 Content-Length"探针和"路由遮蔽"探针发现了两个我之前完全没想到的问题。3.1 和 3.3 都是小范围但致命的 bug——前者让请求体限制形同虚设，后者让对账接口根本调不到。

3.2 关于 rollback 缺锁的问题我也认同——publish 加了锁但 rollback 没加，等于防盗门装了一半。

---

## 逐条修复记录

### 3.1 [必须修复] 虚假 Content-Length 可绕过 → ✅ 已修复

**根因**：中间件在 Content-Length ≤ max 时跳过实际字节计数。

**修复历程（三次迭代）**：
| 版本 | 方案 | 分块超限结果 | 
|------|------|------------|
| V1 | BaseHTTPMiddleware + try/except | 500 ❌ |
| V2 | 纯 ASGI + exception 传播 | 400 ❌ |
| V3 | 纯 ASGI + send 拦截模式 | 413 ✅ |

**最终方案**：所有请求累计实际字节。超限时不抛异常，改用 `exceeded` flag + send 拦截——当 app 试图返回 400 时，在 send 层拦截第一个 `http.response.start`，替换为 413。

**Commit**: `0b25720` → `754d9a7`

### 3.2 [必须修复] rollback 缺锁 + commit 失败无补偿 → ✅ 已修复

**修复内容**：
1. `rollback_config()` 和 `_publish_from_record()` 开头加 `pg_try_advisory_xact_lock(9999)`
2. COS 上传成功后立即 `await db.commit()`（不等 get_db 隐式 commit）
3. commit 失败 → 标记 `cos_upload_status='failed'` + 返回 500

**Commit**: `4c28976`

### 3.3 [必须修复] 对账路由被遮蔽 → ✅ 已修复

**根因**：Starlette 按注册顺序匹配，`/configs/{config_id}` 先匹配 "reconcile"

**修复**：将 `@router.get("/configs/reconcile")` 移到 `@router.get("/configs/{config_id}")` 之前

**Commit**: `6e13e5c`

### 4.1 部署包不含 scripts → ✅ 已修复

打包命令改为 `tar -czf sdk-deploy.tar.gz backend/ scripts/`

**Commit**: `0f8e657`

### 4.2+4.3+4.4 对账接口完善 → ✅ 已修复

- 改用 `httpx.AsyncClient` 替代同步 `urllib`
- 查询加 `cos_upload_status='success'` 条件
- 定时任务记录技术债

**Commit**: `ea24202`

### 4.5 测试覆盖 → ✅ 已修复

新增 13 项测试（请求体限制 10 项 + 发布失败/锁冲突/回滚 3 项）

**Commit**: `24681ee` + `f5d594a`

---

## 测试结果

```
30 passed in 8.53s ✅（旧 17 + 新增 13）
```

## 提交记录

```
754d9a7 fix: 3.1 中间件改用send拦截模式，分块超限稳定返回413
f5d594a test: 4.5 补充发布失败、锁冲突、回滚失败测试
ea24202 fix: 4.2+4.3+4.4 对账接口完善(httpx异步+status过滤+路由修复)
0f8e657 fix: 4.1 部署更新包包含scripts目录
6e13e5c fix: 3.3 对账路由移到动态路由之前，修复路由遮蔽
4c28976 fix: 3.2 rollback加advisory lock+COS后显式commit+失败标记
0b25720 fix: 3.1 所有请求累计实际字节，虚假Content-Length无法绕过
```

---

> 🍔 第四次审阅全部关闭。30 passed, 0 failed。
