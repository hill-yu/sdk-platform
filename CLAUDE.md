# SDK 数据中台 + 配置管理系统

## 项目概述
为移动 App SDK（iOS/Android）提供后端：SDK交互API + 数据中台大盘 + 配置表CDN管理。
技术栈：FastAPI + PostgreSQL + Vue3 + 腾讯云COS/CDN
DAU ~3000，日请求数万级

## 项目结构
D:\code\SDK\
├── docs/          ← 设计文档（01-ARCHITECTURE, 02-API-SPEC, 03-DATABASE, 04-IMPLEMENTATION-PLAN）
├── backend/       ← FastAPI 后端
│   └── app/
│       ├── sdk_main.py       ← SDK API 入口 (端口8100)
│       ├── core/config.py    ← 配置(含ADMIN_TOKEN, COS等)
│       ├── core/database.py  ← async SQLAlchemy engine
│       ├── models/           ← ORM (event, config, version)
│       ├── schemas/          ← Pydantic (sdk_schemas.py)
│       └── api/sdk/          ← SDK 4接口 (version, config→meta, click, log)
├── frontend/      ← Vue3 前端（未创建）
└── scripts/
    └── init_db.sql  ← 数据库初始化

## 关键约定
- 配置分发：CDN为主，API /api/v1/config/meta 仅返回元信息
- 事件字段统一用 element（不用 button）
- 上报语义：部分成功返回 partial_success，不吞错误
- 密码不在文档中写明文，用 ${DB_PASSWORD}
- 分区表 sdk_events 按月分区

## 当前状态
- Python 3.11, 依赖已安装
- PostgreSQL 已启动（localhost:5432），但 sdk_platform 数据库未创建
- SDK API 代码已写但未启动验证

## 需要完成的任务

### Phase 1 收尾（立即）
1. 创建数据库：psql -U postgres -c "CREATE DATABASE sdk_platform;"
2. 执行初始化：psql -U postgres -d sdk_platform -f D:\code\SDK\scripts\init_db.sql
3. 修改 D:\code\SDK\backend\.env 中 DATABASE_URL 的密码为实际 postgres 密码
4. 启动 SDK API：cd D:\code\SDK\backend && python -m app.sdk_main
5. 验证 4 个接口（用 curl）：
   - GET /health
   - GET /api/v1/version?platform=ios&current_version=0
   - POST /api/v1/config/meta {"package_name":"test"}
   - POST /api/v1/click {"package_name":"test","device_id":"dev1","events":[{"type":"click","page":"home","element":"btn"}]}
   - POST /api/v1/log {"package_name":"test","device_id":"dev1","logs":[{"level":"info","message":"test","extra":"raw"}]}

### Phase 2（Phase 1 通过后）
按照 D:\code\SDK\docs\04-IMPLEMENTATION-PLAN.md 中的 Task 2.1~2.7 依次执行：
1. 创建 admin_main.py 入口（端口8101）
2. 实现 dashboard.py（summary/trend/breakdown/events 查询接口）
3. 实现 config_mgr.py 和 version_mgr.py（admin 接口）
4. 初始化 Vue3 前端项目
5. 创建前端路由、布局、暗色主题
6. 实现 Dashboard.vue 数据大盘页面
7. 启动 admin API + 前端验证

## 代码规范
- Python 用类型注解
- 函数加 docstring
- 不引入 Redis/ClickHouse/Kafka
- 不写复杂单元测试
- 不要过度抽象（不要 Repository 模式）

## 验证标准
每个 Phase 完成后必须检查：
- 接口可调用返回正确响应
- 数据可写入数据库
- 页面可渲染无 console 报错
