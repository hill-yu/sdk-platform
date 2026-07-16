# Claude Task: SDK Platform — 剩余开发任务

## 项目位置
D:\code\SDK\

## 设计文档参考
D:\code\SDK\docs\
- 01-ARCHITECTURE.md
- 02-API-SPEC.md
- 03-DATABASE.md
- 04-IMPLEMENTATION-PLAN.md
- 05-PROGRESS-REPORT.md

## 已完成的代码
- backend/app/core/ — config.py, database.py ✅
- backend/app/models/ — event.py, config.py, version.py ✅
- backend/app/schemas/ — sdk_schemas.py ✅
- backend/app/api/sdk/ — version.py, config.py, click.py, log.py ✅
- backend/app/sdk_main.py ✅
- backend/app/admin_main.py ✅
- backend/app/api/admin/ — dashboard.py, config_mgr.py, version_mgr.py, deps.py ✅
- backend/app/services/ — 4个service文件 ✅
- frontend/ — 3个页面 + 3个组件 ✅
- scripts/init_db.sql ✅
- 部分测试文件 ✅

## 需要你完成的任务（按优先级）

### Task 1: 数据库初始化
1. 确认 PostgreSQL 正在运行（已在 :5432 启动）
2. 检查 .env 中的 DATABASE_URL，将 ${DB_PASSWORD} 改为实际密码
3. 如果数据库 sdk_platform 不存在，创建它
4. 执行 scripts/init_db.sql 建表
5. 验证所有表和视图创建成功

### Task 2: 安装依赖
```bash
cd D:\code\SDK\backend
pip install -r requirements.txt
```

### Task 3: 启动 SDK API 并测试
```bash
cd D:\code\SDK\backend
python -m uvicorn app.sdk_main:app --host 0.0.0.0 --port 8100 &
```
用 curl 测试：
- GET /health → {"status":"ok"}
- GET /api/v1/version?platform=ios&current_version=0 → 应返回 has_update=false
- GET /api/v1/config/meta?app_id=test → 应返回 code=0（init数据有published配置）
- POST /api/v1/click → 测试写入
- POST /api/v1/log → 测试写入

### Task 4: 启动 Admin API 并测试
```bash
cd D:\code\SDK\backend
python -m uvicorn app.admin_main:app --host 0.0.0.0 --port 8101 &
```
用 curl 测试（带鉴权头 Authorization: Bearer admin-secret-token-change-me）：
- GET /api/admin/health
- GET /api/admin/dashboard/summary
- GET /api/admin/configs

### Task 5: 修复任何报错
如果启动或测试过程中有错误，修复代码后重新验证。

### Task 6: 前端安装和启动
```bash
cd D:\code\SDK\frontend
# 如果 package.json 不存在，用 npm create vite@latest 初始化
npm install
npm run dev
```

## 关键约束
- 所有代码在 D:\code\SDK\ 下
- Python 3.11，使用 asyncpg + SQLAlchemy async
- 不要新引入 Redis/Celery/Kafka
- 配置/meta 接口只返回元信息，不返回完整 config JSON
- 事件上报支持 partial_success 语义
