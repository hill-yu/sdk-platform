# 🔍 SDK 数据中台 — 文档驱动代码审查报告

> **审查日期**：2026-06-30  
> **审查方法**：对照 `docs/` 下 4 份设计文档 + 1 份实施追踪文档，全面审查代码完整性与正确性  
> **审查范围**：`D:\code\SDK\backend\`（29 个 Python 文件）+ `D:\code\SDK\frontend\src\`（15 个 TS/Vue 文件）+ `D:\code\SDK\scripts\`（SQL/Shell）

---

## 📊 总评

| 维度 | 评分 | 说明 |
|------|------|------|
| 后端 API 完整度 | **8.5/10** | 18 个端点全部实现，无遗漏 |
| 后端正确性 | **7.0/10** | 2 个阻断 bug + 5 个中等偏差 |
| 前端完整度 | **6.5/10** | 骨架完整，核心交互多处缺失 |
| 数据库 DDL | **9.5/10** | 与设计文档高度一致 |
| 配置/环境 | **7.0/10** | `.env.example` 有变量替换陷阱 |
| **综合** | **7.5/10** | 核心链路可用，细节待打磨 |

---

## 一、项目结构完整性

### 1.1 后端文件（对照 `01-ARCHITECTURE.md` 第 4 节）

| 设计要求 | 实际 | 状态 |
|----------|------|------|
| `app/sdk_main.py` (端口8100) | ✅ 存在 | ✅ |
| `app/admin_main.py` (端口8101) | ✅ 存在 | ✅ |
| `app/core/config.py` | ✅ 存在 | ✅ |
| `app/core/database.py` | ✅ 存在 | ✅ |
| `app/models/event.py` | ✅ 存在 | ✅ |
| `app/models/config.py` | ✅ 存在 | ✅ |
| `app/models/version.py` | ✅ 存在 | ✅ |
| `app/schemas/sdk_schemas.py` | ✅ 存在 | ✅ |
| `app/schemas/admin_schemas.py` | ✅ 存在 | ✅ |
| `app/api/sdk/version.py` | ✅ 存在 | ✅ |
| `app/api/sdk/config.py` | ✅ 存在 | ✅ |
| `app/api/sdk/click.py` | ✅ 存在 | ✅ |
| `app/api/sdk/log.py` | ✅ 存在 | ✅ |
| `app/api/admin/dashboard.py` | ✅ 存在 | ✅ |
| `app/api/admin/config_mgr.py` | ✅ 存在 | ✅ |
| `app/api/admin/version_mgr.py` | ✅ 存在 | ✅ |
| `app/api/admin/deps.py` | ✅ 存在 | ✅ |
| `app/services/config_service.py` | ✅ 存在 | ✅ |
| `app/services/version_service.py` | ✅ 存在 | ✅ |
| `app/services/analysis_service.py` | ✅ 存在 | ✅ |
| `app/services/event_service.py` | ❌ **缺失** | ⚠️ 低影响 |
| `tests/conftest.py` | ✅ 存在 | ✅ |
| `tests/test_sdk_api.py` | ✅ 存在 | ✅ |
| `tests/test_admin_api.py` | ✅ 存在 | ✅ |
| `migrations/` | ❌ **缺失** | ⚠️ 低影响 |

### 1.2 前端文件（对照 `01-ARCHITECTURE.md` 第 4 节）

| 设计要求 | 实际 | 状态 |
|----------|------|------|
| `src/main.ts` | ✅ | ✅ |
| `src/App.vue` | ✅ | ✅ |
| `src/router/index.ts` | ✅ | ✅ |
| `src/api/request.ts` | ✅ | ✅ |
| `src/api/dashboard.ts` | ✅ | ✅ |
| `src/api/config.ts` | ✅ | ✅ |
| `src/api/version.ts` | ✅ | ✅ |
| `src/components/AppLayout.vue` | ✅ | ✅ |
| `src/components/StatCard.vue` | ✅ | ✅ |
| `src/components/TrendChart.vue` | ✅ | ✅ |
| `src/views/Dashboard.vue` | ✅ | ⚠️ 功能不完整 |
| `src/views/ConfigManager.vue` | ✅ | ⚠️ 功能不完整 |
| `src/views/VersionManager.vue` | ✅ | ⚠️ 功能不完整 |
| `src/styles/variables.css` | ✅ | ⚠️ 变量不完整 |

### 1.3 脚本文件

| 设计要求 | 实际 | 状态 |
|----------|------|------|
| `scripts/init_db.sql` | ✅ 存在 | ✅ |
| `scripts/deploy.sh` | ❌ **缺失** | ⚠️ 低影响 |

---

## 二、API 端点完整性检查

### 2.1 SDK API（端口 8100）— ✅ 全部实现

| # | 方法 | 路径 | 文件 | 状态 |
|---|------|------|------|------|
| A1 | GET | `/api/v1/version` | `api/sdk/version.py` | ✅ |
| A2 | GET | `/api/v1/config/meta` | `api/sdk/config.py` | ✅ |
| A3 | POST | `/api/v1/click` | `api/sdk/click.py` | ✅ |
| A4 | POST | `/api/v1/log` | `api/sdk/log.py` | ✅ |

### 2.2 Admin API（端口 8101）— ✅ 全部实现

| # | 方法 | 路径 | 文件 | 状态 |
|---|------|------|------|------|
| B1.1 | GET | `/api/admin/dashboard/summary` | `admin/dashboard.py` | ✅ |
| B1.2 | GET | `/api/admin/dashboard/trend` | `admin/dashboard.py` | ✅ |
| B1.3 | GET | `/api/admin/dashboard/breakdown` | `admin/dashboard.py` | ✅ |
| B1.4 | GET | `/api/admin/events` | `admin/dashboard.py` | ✅ |
| B2.1 | GET | `/api/admin/configs` | `admin/config_mgr.py` | ✅ |
| B2.2 | GET | `/api/admin/configs/{id}` | `admin/config_mgr.py` | ✅ |
| B2.3 | POST | `/api/admin/configs` | `admin/config_mgr.py` | ✅ |
| B2.4 | PUT | `/api/admin/configs/{id}` | `admin/config_mgr.py` | ✅ |
| B2.5 | POST | `/api/admin/configs/{id}/publish` | `admin/config_mgr.py` | ✅ |
| B2.6 | POST | `/api/admin/configs/{id}/rollback` | `admin/config_mgr.py` | ✅ |
| B3.1 | GET | `/api/admin/versions` | `admin/version_mgr.py` | ✅ |
| B3.2 | POST | `/api/admin/versions` | `admin/version_mgr.py` | ✅ |
| B3.3 | PUT | `/api/admin/versions/{id}` | `admin/version_mgr.py` | ❌ BUG |

---

## 三、问题详细清单

### 🔴 阻断性问题（必须修复）

#### #1 后端：`version_mgr.py` 调用 `update_version` 缺少 `db` 参数

- **严重度**：🔴 阻断 — 运行时 TypeError
- **文件**：`backend/app/api/admin/version_mgr.py` 第 31 行
- **问题**：

```python
# ❌ 当前代码
data = await version_service.update_version(version_id, payload.model_dump(...))

# ✅ 函数签名要求
async def update_version(db: AsyncSession, version_id: int, payload: dict) -> dict:
```

- **影响**：`PUT /api/admin/versions/{id}` 接口调用即崩溃，完全不可用
- **修复**：在调用处加上 `db` 参数

```python
data = await version_service.update_version(db, version_id, payload.model_dump(...))
```

---

#### #2 后端：`rollback_config` 生成新版本号而非保留原版本号

- **严重度**：🔴 阻断 — 语义错误
- **文件**：`backend/app/services/config_service.py` 第 78-103 行 `_publish_from_record()`
- **问题**：回滚调用 `_publish_from_record`，该函数**总是生成新的时间戳版本号**，覆盖了原 `archived` 配置的 `version` 字段
- **影响**：回滚后无法追溯到原始版本号，文档 B2.6 明确要求返回 `"version": "20260629_v2"`
- **修复**：在 `_publish_from_record` 中区分场景：
  - 首次发布（原 status == draft）→ 生成新版本号
  - 回滚（原 status == archived）→ 保留 `config.version` 不变

---

#### #3 前端：`ConfigManager.vue` — `saveDraft()` 无异常处理

- **严重度**：🔴 阻断 — 页面崩溃
- **文件**：`frontend/src/views/ConfigManager.vue` `saveDraft()` 函数
- **问题**：

```typescript
// ❌ JSON.parse 抛出 SyntaxError 时页面崩溃
const payload = { config_data: JSON.parse(editorValue.value), ... };
```

- **修复**：用 try-catch 包裹，校验失败时 toast 提示而非崩溃

```typescript
try {
  const parsed = JSON.parse(editorValue.value);
  await updateConfig(editingId.value, { config_data: parsed, ... });
} catch (e) {
  alert("配置 JSON 格式错误，请检查后重试");
}
```

---

#### #4 环境：`.env.example` 中 `${DB_PASSWORD}` 不会被展开

- **严重度**：🔴 阻断 — 数据库连接失败
- **文件**：`backend/.env.example` 第 1 行
- **问题**：

```env
# ❌ Shell 语法，pydantic-settings 不展开
DATABASE_URL=postgresql+asyncpg://admin:${DB_PASSWORD}@localhost:5432/sdk_platform
```

- **影响**：如果用户直接复制 `.env.example` 为 `.env`，密码字面是 `${DB_PASSWORD}`，数据库连接失败
- **修复方案**（二选一）：
  - **A**：在 `config.py` 中用 `@property` 动态拼接 URL
  - **B**：`.env.example` 中直接用占位明文密码，加注释说明

---

### 🟠 高优先级问题

| # | 位置 | 问题 | 影响 |
|---|------|------|------|
| 5 | 前端 `Dashboard.vue` 事件明细表 | **无分页控件**：`loadEvents()` 写死 `page_size=8`，无页码切换 | 数据量大时无法浏览 |
| 6 | 前端 `Dashboard.vue` 事件明细表 | **无可展开行**：设计要求"点击行可展开查看 payload 完整 JSON" | 核心功能缺失 |
| 7 | 前端 `Dashboard.vue` 事件明细表 | **无筛选栏**：缺少日期范围、事件类型、app_id 筛选器 | 核心功能缺失 |
| 8 | 前端 `VersionManager.vue` | **缺少启用/停用功能**：仅"编辑"按钮 | 设计文档明确要求 |
| 9 | 前端 `VersionManager.vue` | **表单非弹窗**：是页面底部内联区域，设计要求"弹窗表单(dialog)" | 不符合设计 |
| 10 | 前端全部页面 | **无异常处理**：所有 API 调用直接 await，网络异常静默失败 | 用户体验差 |

---

### 🟡 中等问题

| # | 位置 | 问题 |
|---|------|------|
| 11 | 后端 `analysis_service.py:34-35` | `today_pv` 与 `today_events` 返回相同值（都取自 `today_events`），文档中两者不同（12580 vs 45230） |
| 12 | 后端 `api/sdk/config.py:31` | `GET /config/meta` 接收 `app_id` 必填参数但不参与查询过滤 |
| 13 | 后端 `api/sdk/log.py:43-53` | 创建 SdkEvent 时未传入 `session_id` 和 `user_agent` |
| 14 | 后端 `api/sdk/version.py:55` | 无更新时返回 `latest.version_code` 而非请求的 `current_version` |
| 15 | 前端 `variables.css` | 缺少 `--bg-secondary`(#16213e) 和 `--accent`(#0f3460) |
| 16 | 前端 `api/request.ts:9` | Token fallback 硬编码 `"admin-secret-token-change-me"` |
| 17 | 前端 `VersionManager.vue` | 表单缺少 `file_size` / `file_hash` 字段 |
| 18 | 前端 `ConfigManager.vue` | 顶部信息区缺少"发布时间"(`publish_at`) 显示 |

---

### 🟢 轻微问题 / 改进建议

| # | 位置 | 问题 |
|---|------|------|
| 19 | 后端 `config_service.py:106-109` | COS 上传为占位实现（Phase 3 TODO） |
| 20 | 后端 `admin_main.py:22` | ETL 刷新异常被 `pass` 吞掉，建议 `logging.warning` |
| 21 | 后端 | `migrations/` 目录不存在（Alembic 迁移） |
| 22 | 后端 | `services/event_service.py` 文件不存在（功能内聚在 API 层） |
| 23 | 后端 ORM vs DDL | `event.py` 中 `event_type` 建了单列索引，DDL 是复合索引 `(event_type, server_ts DESC)` |
| 24 | 前端三个页面 | 均无 loading / empty / error 状态 |
| 25 | 前端 `TrendChart.vue` | ECharts 饼图 legend 在暗色背景下可能不可见 |
| 26 | 脚本 | `deploy.sh` 不存在 |

---

## 四、数据库 DDL 审查结果

### ✅ 完全一致的部分
- `sdk_events` 表结构（分区、列类型、PRIMARY KEY、6 个索引）
- `sdk_configs` 表结构（UK、CHECK、部分唯一索引）
- `sdk_versions` 表结构（UK、3 个 CHECK）
- 物化视图 `mv_daily_event_stats`、`mv_hourly_trend`
- `refresh_materialized_views()` 刷新函数
- 分区维护函数
- 初始数据 INSERT

### ⚠️ 细微差异
- COMMENT 注释被简化（功能无影响）
- `create_next_partition()` 返回值少了起止日期（功能无影响）
- 添加了 `IF NOT EXISTS`（防御性改进，正确）

**结论**：DDL 无语法错误，可直接执行。

---

## 五、架构决策对照

| 决策 | 文档要求 | 代码实现 | 状态 |
|------|----------|----------|------|
| 决策1 | 两个独立 FastAPI 进程 | `sdk_main.py:8100` + `admin_main.py:8101` | ✅ |
| 决策2 | 事件用 JSONB 灵活存储 | `payload JSONB`，无预定义字段 | ✅ |
| 决策3 | 配置走 CDN，API 仅返元信息 | `/config/meta` 只返回 `version/updated_at/cdn_url` | ✅ |
| 决策4 | 不引入 Redis/ClickHouse/MQ | 纯 PG + async SQLAlchemy | ✅ |
| CORS | Admin API 需要 | `allow_origins=["*"]` 已配置 | ✅ |
| ETL | 每 5 分钟刷新物化视图 | `etl_refresh_loop()` 已实现 | ✅ |
| 鉴权 | Admin API 固定 Token | `deps.py` Bearer Token 验证 | ✅ |

---

## 六、修复清单（按优先级排序）

### 🚨 立即修复（阻断）

- [x] ~~审查完成~~ → 2026-06-30
- [ ] **修复 #1**：`version_mgr.py:31` 补充 `db` 参数 → `api/admin/version_mgr.py`
- [ ] **修复 #2**：`_publish_from_record()` 回滚时保留原版本号 → `services/config_service.py`
- [ ] **修复 #3**：`ConfigManager.vue` `saveDraft()` 加 try-catch → `views/ConfigManager.vue`
- [ ] **修复 #4**：纠正 `.env.example` 的 `DATABASE_URL` → `.env.example` / `config.py`

### 🔜 尽快修复（高优先）

- [ ] **修复 #5-7**：Dashboard 事件明细表加分页、展开行、筛选栏 → `views/Dashboard.vue`
- [ ] **修复 #8**：VersionManager 添加启用/停用功能 → `views/VersionManager.vue` + `api/version.ts`
- [ ] **修复 #9**：VersionManager 表单改为弹窗 → `views/VersionManager.vue`
- [ ] **修复 #10**：全局 API 调用加错误处理 → 三个 View 组件
- [ ] **修复 #15**：补齐 CSS 变量 → `styles/variables.css`

### 📅 计划修复（中优先）

- [ ] **修复 #11**：区分 `today_pv` 与 `today_events` 查询逻辑 → `services/analysis_service.py`
- [ ] **修复 #12**：`/config/meta` 用 `app_id` 过滤或标注忽略 → `api/sdk/config.py`
- [ ] **修复 #13**：`log.py` 补充 `session_id`/`user_agent` 写入 → `api/sdk/log.py`
- [ ] **修复 #14**：对齐无更新时的响应字段 → `api/sdk/version.py`
- [ ] **修复 #16**：移除 Token 硬编码 fallback → `api/request.ts`
- [ ] **修复 #17**：版本表单补齐 `file_size`/`file_hash` → `views/VersionManager.vue`
- [ ] **修复 #18**：配置详情显示发布时间 → `views/ConfigManager.vue`

### 📅 计划修复（低优先）

- [ ] **修复 #19**：接入腾讯云 COS SDK → `services/config_service.py`
- [ ] **修复 #20**：ETL 异常加 logging → `admin_main.py`
- [ ] **修复 #21**：创建 Alembic 迁移目录 → `backend/migrations/`
- [ ] **修复 #23**：ORM 索引与 DDL 对齐 → `models/event.py`
- [ ] **修复 #24**：三页面加 loading/empty/error 状态
- [ ] **修复 #25**：ECharts 暗色适配 → `components/TrendChart.vue`
- [ ] **修复 #26**：创建部署脚本 → `scripts/deploy.sh`

---

## 七、测试覆盖

### 现有测试（12 个）✅
- 版本查询空表场景、ETag 304、配置元信息返回
- 点击上报部分成功、日志级别校验、日志正常写入
- Admin 鉴权拦截、Dashboard 概览
- 配置列表、发布、回滚、版本列表

### 缺失测试场景
- ❌ `/version` 有更新时的完整响应
- ❌ `/click` 超 100 条事件校验
- ❌ `/config/meta` 无已发布配置返回 `code=1`
- ❌ Dashboard trend / breakdown / events 接口
- ❌ 版本编辑（当前因 bug #1 无法测试）
- ❌ 配置 create / update / 404

---

> 🍔 **报告生成**：2026-06-30 | 审查耗时 ~20 分钟 | 三个子代理并行审查  
> **下一步**：请确认修复优先级，我可以立即开始修复阻断性 bug
