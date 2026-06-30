# SDK 平台实现计划

> **面向 AI 代理的工作说明：** 按修订后的 `docs/01-ARCHITECTURE.md`、`docs/02-API-SPEC.md`、`docs/03-DATABASE.md`、`docs/04-IMPLEMENTATION-PLAN.md` 实现功能。优先遵循 TDD；每完成一个阶段都运行对应验证命令。
**目标：** 实现 SDK 数据中台与配置管理系统的后端核心链路、管理后台 API、前端页面和基础验证能力。

**架构：** 保留双 FastAPI 进程方案；SDK 配置通过 CDN 分发，业务 API 仅返回配置元信息；管理后台接口增加固定 Token 鉴权；数据分析基于 PostgreSQL 明细表和物化视图完成。

**技术栈：** FastAPI、SQLAlchemy Async、PostgreSQL 15+、Vue 3、Vite、ECharts、Axios。

---

### 任务 1：补齐后端项目结构与基础配置

**文件：**
- 修改：`backend/app/core/config.py`
- 修改：`backend/app/core/database.py`
- 修改：`backend/requirements.txt`
- 创建：`backend/.env.example`
- 创建：`backend/app/__init__.py`
- 创建：`backend/app/api/__init__.py`
- 创建：`backend/app/api/sdk/__init__.py`
- 创建：`backend/app/api/admin/__init__.py`
- 创建：`backend/app/models/__init__.py`
- 创建：`backend/app/schemas/__init__.py`
- 创建：`backend/app/services/__init__.py`
- 创建：`backend/tests/`

- [ ] 统一后端配置项，确保包含 `ADMIN_TOKEN`、`DB_PASSWORD` 替代方案和文档要求的端口配置。
- [ ] 修正数据库会话管理与字符串格式问题，保证 `.env` 可被本地开发直接使用。
- [ ] 补齐缺失目录和 `__init__.py`，让后续模块导入稳定。

### 任务 2：修复数据库脚本与 ORM 对齐问题

**文件：**
- 修改：`scripts/init_db.sql`
- 修改：`backend/app/models/event.py`
- 修改：`backend/app/models/config.py`
- 修改：`backend/app/models/version.py`

- [ ] 修复 `init_db.sql` 中当前存在的注释、字符串、返回格式和物化视图字段问题。
- [ ] 确认 `sdk_events`、`sdk_configs`、`sdk_versions` 的 ORM 与 DDL 一致。
- [ ] 验证物化视图统计字段统一使用 `element`。

### 任务 3：用 TDD 完成 SDK 侧接口与基础测试

**文件：**
- 修改：`backend/app/schemas/sdk_schemas.py`
- 修改：`backend/app/api/sdk/version.py`
- 修改：`backend/app/api/sdk/config.py`
- 修改：`backend/app/api/sdk/click.py`
- 修改：`backend/app/api/sdk/log.py`
- 修改：`backend/app/sdk_main.py`
- 创建：`backend/tests/conftest.py`
- 创建：`backend/tests/test_sdk_api.py`

- [ ] 先写 SDK API 测试，覆盖版本查询、配置元信息、点击上报、日志上报的成功与失败语义。
- [ ] 再修正 SDK 路由实现，使其满足最新接口契约。
- [ ] 验证 `/api/v1/config/meta`、`partial_success`、HTTP 400/500 语义是否符合文档。

### 任务 4：实现管理后台鉴权、服务层与 API

**文件：**
- 创建：`backend/app/schemas/admin_schemas.py`
- 创建：`backend/app/api/admin/dashboard.py`
- 创建：`backend/app/api/admin/config_mgr.py`
- 创建：`backend/app/api/admin/version_mgr.py`
- 创建：`backend/app/api/admin/deps.py`
- 创建：`backend/app/services/config_service.py`
- 创建：`backend/app/services/analysis_service.py`
- 创建：`backend/app/services/version_service.py`
- 创建：`backend/app/admin_main.py`
- 创建：`backend/tests/test_admin_api.py`

- [ ] 先写管理后台 API 测试，覆盖鉴权、数据大盘、配置管理、版本管理与回滚逻辑。
- [ ] 实现固定 Token 鉴权依赖，并挂载到全部 `/api/admin/*` 路由。
- [ ] 实现配置发布与回滚时同步更新 `config/latest.json` 的逻辑，Phase 当前先保留可替换的上传实现。
- [ ] 实现 ETL 刷新任务启动逻辑。

### 任务 5：搭建前端工程并实现页面

**文件：**
- 创建：`frontend/package.json`
- 创建：`frontend/tsconfig.json`
- 创建：`frontend/tsconfig.node.json`
- 创建：`frontend/vite.config.ts`
- 创建：`frontend/index.html`
- 创建：`frontend/src/main.ts`
- 创建：`frontend/src/App.vue`
- 创建：`frontend/src/router/index.ts`
- 创建：`frontend/src/api/request.ts`
- 创建：`frontend/src/api/dashboard.ts`
- 创建：`frontend/src/api/config.ts`
- 创建：`frontend/src/api/version.ts`
- 创建：`frontend/src/components/AppLayout.vue`
- 创建：`frontend/src/components/StatCard.vue`
- 创建：`frontend/src/components/TrendChart.vue`
- 创建：`frontend/src/views/Dashboard.vue`
- 创建：`frontend/src/views/ConfigManager.vue`
- 创建：`frontend/src/views/VersionManager.vue`
- 创建：`frontend/src/styles/variables.css`

- [ ] 初始化 Vue 3 + Vite + TypeScript 工程配置。
- [ ] 实现管理后台路由、基础布局、Dashboard、配置管理、版本管理页面。
- [ ] 前端严格对齐最新接口：配置页面调用发布/回滚；Dashboard 使用 `yesterday_*` 字段计算涨跌。

### 任务 6：验证与收尾

**文件：**
- 修改：相关实现文件按验证结果收尾

- [ ] 安装依赖并运行后端测试。
- [ ] 运行前端构建或类型检查，确认页面工程可编译。
- [ ] 如本地具备 PostgreSQL，执行数据库初始化并做基本接口验证；若本地缺少环境，明确记录阻塞点。
- [ ] 最终对照 4 份文档逐项核对实现范围，确认没有遗漏关键契约。
