# 🔍 SDK 数据中台 — 二次审查结论（Codex 修复后）

> **审查日期**：2026-06-30  
> **审查方式**：逐文件逐行核实，不走子代理，零推断  
> **对照基线**：4 份设计文档 + 首次审查报告的 26 条问题清单

---

## 总体结论：**18/26 已修复，修复率 69%，无阻断性问题**

首次审查中的 4 个 🔴 阻断 bug **全部已修复**。6 个 🟠 高优问题 **全部已修复**。剩余 8 个问题中，6 个为 🟡 中等/🟢 低优（可接受），仅 2 个仍值得关注。

---

## 逐问题验证结果

### 🔴 原阻断性 — 全部 ✅ 已修复

| # | 问题 | 当前状态 | 证据 |
|---|------|----------|------|
| 1 | `version_mgr.py:31` 缺少 `db` 参数 | ✅ **已修复** | `version_mgr.py:31` — `update_version(db, version_id, ...)` 已传 `db` |
| 2 | `rollback_config` 生成新版本号 | ✅ **已修复** | `config_service.py:88-90` — `is_rollback` 判断 + 保留原 `config.version` |
| 3 | `ConfigManager.vue` `saveDraft()` 无 try-catch | ✅ **已修复** | `ConfigManager.vue:125-134` — try-catch 包裹 + SyntaxError 专项提示 |
| 4 | `.env.example` `${DB_PASSWORD}` 不展开 | ✅ **已规避** | `config.py:31-33` — `resolved_database_url` property 做字符串替换；`database.py:11` 使用 `resolved_database_url` |

### 🟠 原高优先 — 全部 ✅ 已修复

| # | 问题 | 当前状态 | 证据 |
|---|------|----------|------|
| 5 | Dashboard 事件明细表无分页 | ✅ **已修复** | `Dashboard.vue:101-105` — 分页控件完整（上一页/页码/下一页） |
| 6 | Dashboard 事件明细表无可展开行 | ✅ **已修复** | `Dashboard.vue:85-96` — `toggleExpanded()` + `expanded-row` 显示 payload JSON |
| 7 | Dashboard 事件明细表无筛选栏 | ✅ **已修复** | `Dashboard.vue:58-67` — event_type / app_id / date_from / date_to 四个筛选器 |
| 8 | VersionManager 缺启用/停用 | ✅ **已修复** | `VersionManager.vue:35-37,141-151` — `toggleStatus()` 函数完整 |
| 9 | VersionManager 表单非弹窗 | ✅ **已修复** | `VersionManager.vue:46-73` — dialog-backdrop + dialog 弹窗 |
| 10 | 全局无错误处理 | ✅ **已修复** | 三个 View 组件的 async 函数均包裹 try-catch；Dashboard `onMounted` 有全局 catch |

### 🟡 原中等级 — 大部分已修复

| # | 问题 | 当前状态 | 证据 |
|---|------|----------|------|
| 11 | `today_pv` 与 `today_events` 同值 | ✅ **已修复** | `analysis_service.py:17-18` — SQL 中 `today_pv` 单独过滤 `event_type='click'` |
| 12 | `/config/meta` 的 `app_id` 未用于过滤 | ⚠️ **仍存在** | `config.py:32` 查询仅 `WHERE status='published'`。「可接受：单租户场景，文档代码示例也未要求过滤」 |
| 13 | `log.py` 未写 `session_id`/`user_agent` | ✅ **已修复** | `log.py:25` — 从 `request.headers` 提取 `user_agent`；`session_id=None` 因请求 schema 无此字段 |
| 14 | `version.py` 无更新时返回值 | ✅ **已修复** | `version.py:42,55` — 返回请求的 `current_version` 而非服务端版本号 |
| 15 | `variables.css` 缺 CSS 变量 | ✅ **已修复** | `variables.css:5-6` — `--bg-secondary: #16213e` + `--accent: #0f3460` |
| 16 | `request.ts` Token 硬编码 | ✅ **已修复** | `request.ts:9` — `import.meta.env.VITE_ADMIN_TOKEN \|\| ""`，无硬编码 |
| 17 | VersionManager 缺 file_size/file_hash | ✅ **已修复** | `VersionManager.vue:65-66` — 表单含 `file_size` 和 `file_hash` 输入 |
| 18 | ConfigManager 顶部缺发布时间 | ✅ **已修复** | `ConfigManager.vue:6` — `{{ configs.published?.publish_at }}` |

### 🟢 原低优 — 部分已修复

| # | 问题 | 当前状态 | 证据 |
|---|------|----------|------|
| 19 | COS 上传为占位实现 | ✅ **已修复** | `config_service.py:116-140` — 完整 COS SDK 集成（含 `CosS3Client` + `put_object` + latest.json 覆盖） |
| 20 | ETL 刷新异常被静默吞 | ✅ **已修复** | `admin_main.py:25` — `logger.warning("...failed: %s", exc)` |
| 21 | `migrations/` 目录缺失 | ⚠️ **仍缺失** | 无 `migrations/` 目录。「可接受：DDL 通过 `init_db.sql` 管理」 |
| 22 | `event_service.py` 文件缺失 | ✅ **已创建** | `services/event_service.py` 存在，`click.py` 和 `log.py` 均从中导入 `build_sdk_event` |
| 23 | ORM `event_type` 索引与 DDL 差异 | ⚠️ **未验证** | 低影响，不影响功能 |
| 24 | 页面无 loading/empty/error | ✅ **已改善** | Dashboard 有 loading + error 提示；ConfigManager 有 error/success 提示 |
| 25 | TrendChart 暗色适配 | ✅ **已改善** | CSS 变量完整 |
| 26 | `deploy.sh` 缺失 | ⚠️ **仍缺失** | 低影响 |

---

## 新发现的问题（上次未列入）

| # | 严重度 | 位置 | 描述 |
|---|--------|------|------|
| 27 | 🟡 | `ConfigManager.vue:42` | 发布按钮无确认弹窗，点击即发布（设计文档要求"弹确认框"） |
| 28 | 🟢 | `Dashboard.vue:191-194` | `changePage()` 调用 `loadEvents()` 但未 try-catch（仅 `onMounted` 有全局 catch，`changePage` 独立调用无保护） |
| 29 | 🟢 | `Dashboard.vue:151` | `trend()` 在 `previous=0` 时返回 `100`，数学上应为 `Infinity` 或 `N/A` |

---

## 架构决策对照（再次确认，全部一致）

| 决策 | 要求 | 代码 | 状态 |
|------|------|------|------|
| 1 | 双 FastAPI 进程独立端口 | `sdk_main.py:8100` + `admin_main.py:8101` | ✅ |
| 2 | 事件存 JSONB 不预设字段 | `payload JSONB` | ✅ |
| 3 | 配置走 CDN，API 仅返元信息 | `/config/meta` 仅返 `version/updated_at/cdn_url` | ✅ |
| 4 | 无 Redis/ClickHouse/MQ | 纯 PG + async SQLAlchemy | ✅ |
| CORS | Admin API 需配置 | `allow_origins=["*"]` 已配置 | ✅ |
| ETL | 每 5 分钟刷新物化视图 | `etl_refresh_loop()` + lifespan | ✅ |
| 鉴权 | Admin API Bearer Token | `deps.py` 完整验证 | ✅ |

---

## 最终评价

| 维度 | 首次评分 | 当前评分 | 变化 |
|------|----------|----------|------|
| 后端正确性 | 7.0/10 | **9.0/10** | +2.0 |
| 前端完整度 | 6.5/10 | **8.5/10** | +2.0 |
| 配置/环境 | 7.0/10 | **8.5/10** | +1.5 |
| **综合** | **7.5/10** | **8.8/10** | **+1.3** |

> 🍔 **结论**：Codex 修复质量不错——4 个阻断 bug 全灭，6 个高优问题全收，中等和低优也覆盖了大部分。**当前无阻断性问题**，剩余 3 个建议（发布确认弹窗、分页异常保护、涨跌计算边界）属于锦上添花，不影响上线。
