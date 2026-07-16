# 对 14-SECOND-REVIEW-REPORT-20260716.md 的分析反馈

> 日期：2026-07-16 | 分析人：汉堡包 🍔

---

## 总体评价

审阅人通过运行时探针（分块请求绕过、非法 Content-Length → 500）和数据库迁移检查，发现了 3.4 修复的"半成品"问题——我加了 `cos_upload_status` 字段但没改 SDK 查询条件，相当于门锁装好了但钥匙还插在门上。

**接受全部 3 项"必须修复"和 4 项"建议修改"。**

---

## 逐条分析

### 3.1 [必须修复] COS 失败配置仍对 SDK 可见 — ✅ 认同

**根因**：`config/meta` 接口只查 `status='published'`，没查 `cos_upload_status`。我上轮的 3.4 修复只解决了一半。

**选择方案 B（最小改动）**：
1. SDK 查询条件改为 `status='published' AND cos_upload_status='success'`
2. 发布流程中，先上传 COS 成功，再归档旧配置（而非先归档再上传）
3. 上传失败时什么都不改，不归档旧配置
4. 不引入 `publishing` 中间状态（保持简洁）

### 3.2 [必须修复] 缺数据库迁移 — ✅ 认同，我漏了

**修复**：创建 `scripts/migrate_cos_upload_status.sql`，提供 ALTER TABLE + 数据回填 + CHECK 约束。同步更新 `init_db.sql`。

### 3.3 [必须修复] 请求体限制可绕过 — ✅ 认同

**修复**：
1. ASGI 层累计实际读取字节数，超限 → 413
2. 非法 Content-Length → 400（非 500）
3. Nginx 配置 `client_max_body_size`
4. 加测试用例

### 4.1 Service 与 DB 依赖混合管理事务 — 认同，但本次不改架构

当前提交模式虽然"不优雅"，但实际运作正确。重构事务边界风险高于收益。记录为技术债，后续迭代处理。

### 4.2 Admin API 未暴露 COS 上传状态 — ✅ 认同

`_serialize_config()` 加 `cos_upload_status` 字段，前端显示状态标签。

### 4.3 测试桩吞异常 — ✅ 认同

`except Exception: pass` 改为只捕获预期异常。

### 4.4 缺少 CHECK 约束 — ✅ 随 3.2 一并修复

---

> 🍔 分析完。逐项修复。
