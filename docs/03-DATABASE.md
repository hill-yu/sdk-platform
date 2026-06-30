# SDK 数据中台 + 配置管理系统 — 数据库设计

> 版本 v1.0 | PostgreSQL 15+ | 给 Codex 的执行文档

---

## 1. 数据库基本信息

| 项 | 值 |
|----|-----|
| 数据库名 | `sdk_platform` |
| 用户名 | `admin` |
| 密码 | 通过环境变量注入（开发环境使用本地 `.env`，生产环境使用密钥管理） |
| 字符集 | UTF8 |
| 时区 | `Asia/Shanghai` |

### 创建数据库

```sql
CREATE DATABASE sdk_platform
  WITH OWNER = admin
       ENCODING = 'UTF8'
       LC_COLLATE = 'en_US.UTF-8'
       LC_CTYPE = 'en_US.UTF-8';
```

---

## 2. ER 图

```
┌─────────────────┐
│   sdk_events    │  原始事件表（按月分区，JSONB 灵活存储）
│                 │
│ PK id           │
│    event_type   │── 'click' | 'log' | 'page_view' | ...
│    app_id       │
│    device_id    │
│    sdk_version  │
│    session_id   │
│    payload      │── JSONB: 完整事件数据
│    client_ts    │
│    server_ts    │── 分区键
│    ip           │
│    user_agent   │
└─────────────────┘

┌─────────────────┐
│  sdk_configs    │  配置表版本记录
│                 │
│ PK id           │
│ UK version      │── 版本号: "20260630_v3" / "draft_20260630..."
│    config_data  │── JSONB: 完整配置内容
│    status       │── 'draft' | 'published' | 'archived'
│    publish_at   │
│    published_by │
│    cos_key      │
│    cdn_url      │
│    change_log   │
│    created_at   │
│    updated_at   │
└─────────────────┘
   ↑ 同时最多 1 条 published（部分唯一索引保证）

┌─────────────────┐
│  sdk_versions   │  SDK 版本管理
│                 │
│ PK id           │
│ UK (platform,   │
│     version_code)│
│    platform     │── 'ios' | 'android'
│    version_code │── 数字版本号（用于比较大小）
│    version_name │── 展示版本号 "1.2.0"
│    update_policy│── 'force' | 'suggest' | 'silent'
│    download_url │
│    release_notes│
│    min_sdk_version│
│    file_size    │
│    file_hash    │
│    status       │── 'active' | 'inactive'
│    created_at   │
│    updated_at   │
└─────────────────┘

┌──────────────────────┐
│ mv_daily_event_stats │  物化视图 — 每日统计
│ mv_hourly_trend      │  物化视图 — 每小时趋势
└──────────────────────┘
```

---

## 3. 建表 DDL（完整可执行 SQL）

### 3.1 sdk_events — 原始事件表

```sql
-- 必须开启的扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- 主表（分区父表，不直接存数据）
-- ============================================================
CREATE TABLE sdk_events (
    id              BIGSERIAL,
    event_type      VARCHAR(50)   NOT NULL,   -- 'click' | 'log' | 'page_view'
    app_id          VARCHAR(32)   NOT NULL,   -- 应用 ID
    device_id       VARCHAR(64),              -- 设备 ID
    sdk_version     VARCHAR(20),              -- SDK 版本
    session_id      VARCHAR(64),              -- 会话 ID
    payload         JSONB         NOT NULL,   -- 完整事件数据
    client_ts       TIMESTAMPTZ,              -- 客户端时间
    server_ts       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),  -- 服务端时间（分区键）
    ip              INET,                     -- 客户端 IP
    user_agent      TEXT,                     -- User-Agent

    CONSTRAINT pk_sdk_events PRIMARY KEY (id, server_ts)
) PARTITION BY RANGE (server_ts);

-- ============================================================
-- 创建当月 + 未来 2 个月的分区
-- ============================================================
DO $$
DECLARE
    base_month DATE := date_trunc('month', NOW())::DATE;
    t_name     TEXT;
    t_start    TEXT;
    t_end      TEXT;
BEGIN
    FOR i IN 0..2 LOOP
        t_name  := 'sdk_events_' || to_char(base_month + (i || ' month')::INTERVAL, 'YYYYMM');
        t_start := to_char(base_month + (i || ' month')::INTERVAL, 'YYYY-MM-DD');
        t_end   := to_char(base_month + ((i+1) || ' month')::INTERVAL, 'YYYY-MM-DD');

        EXECUTE format('
            CREATE TABLE IF NOT EXISTS %I PARTITION OF sdk_events
            FOR VALUES FROM (%L) TO (%L)',
            t_name, t_start, t_end
        );
    END LOOP;
END $$;

-- ============================================================
-- 索引（在父表上建会自动应用到现有和未来的分区）
-- ============================================================
-- 按事件类型 + 时间查询（数据大盘核心索引）
CREATE INDEX idx_events_type_ts ON sdk_events (event_type, server_ts DESC);

-- 按设备查询
CREATE INDEX idx_events_device ON sdk_events (device_id, server_ts DESC);

-- 按应用查询
CREATE INDEX idx_events_app ON sdk_events (app_id, server_ts DESC);

-- 按会话查询
CREATE INDEX idx_events_session ON sdk_events (session_id, server_ts DESC);

-- JSONB 内部字段查询（GIN 索引，支持 payload->>'page' 等操作符）
CREATE INDEX idx_events_payload ON sdk_events USING GIN (payload jsonb_path_ops);

-- 按客户端时间查询
CREATE INDEX idx_events_client_ts ON sdk_events (client_ts DESC);

-- ============================================================
-- 注释
-- ============================================================
COMMENT ON TABLE sdk_events IS 'SDK原始事件表（按月分区）。event_type区分事件类型，payload用JSONB灵活存储具体字段。';
COMMENT ON COLUMN sdk_events.payload IS 'JSONB示例:
  click:    {"page":"home","element":"buy_btn","x":100,"y":200,"extra":{}}
  page_view:{"page":"home","duration_ms":5000,"from":"push","extra":{}}
  log:      {"level":"error","tag":"Network","message":"timeout","extra":{"stack":"..."}}';
```

### 3.2 sdk_configs — 配置表版本记录

```sql
CREATE TABLE sdk_configs (
    id              SERIAL PRIMARY KEY,
    version         VARCHAR(32)   NOT NULL,      -- 版本号: "20260630_v3" 或 "draft_20260630120000"
    config_data     JSONB         NOT NULL,      -- 完整配置 JSON
    status          VARCHAR(20)   NOT NULL DEFAULT 'draft',  -- draft / published / archived
    publish_at      TIMESTAMPTZ,                 -- 发布时间
    published_by    VARCHAR(64),                 -- 发布人
    cos_key         VARCHAR(256),                -- COS 对象路径: "config/v20260630_v3.json"
    cdn_url         VARCHAR(512),                -- CDN 访问地址
    change_log      TEXT,                        -- 变更说明
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_configs_version UNIQUE (version),
    CONSTRAINT chk_configs_status CHECK (status IN ('draft', 'published', 'archived'))
);

-- 确保同时最多 1 条 published
CREATE UNIQUE INDEX uq_configs_one_published ON sdk_configs (status) WHERE status = 'published';

-- 索引
CREATE INDEX idx_configs_status ON sdk_configs (status, created_at DESC);

COMMENT ON TABLE sdk_configs IS '配置表版本记录。同时最多1条published。支持草稿→发布→回滚。';
COMMENT ON COLUMN sdk_configs.config_data IS 'SDK同事定义的配置内容JSON，后台只做透传和版本管理。';
```

### 3.3 sdk_versions — SDK 版本管理

```sql
CREATE TABLE sdk_versions (
    id              SERIAL PRIMARY KEY,
    platform        VARCHAR(10)   NOT NULL,      -- 'ios' | 'android'
    version_code    INTEGER       NOT NULL,      -- 数字版本号，用于比较大小
    version_name    VARCHAR(20)   NOT NULL,      -- 展示版本号 "1.2.0"
    update_policy   VARCHAR(20)   NOT NULL DEFAULT 'suggest',  -- force | suggest | silent
    download_url    VARCHAR(512),                -- 下载地址
    release_notes   TEXT,                        -- 更新日志
    min_sdk_version INTEGER,                     -- 最低兼容 SDK 版本（version_code）
    file_size       BIGINT,                      -- 文件大小(字节)
    file_hash       VARCHAR(64),                 -- 文件 SHA256
    status          VARCHAR(20)   NOT NULL DEFAULT 'active',  -- active | inactive
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_versions_platform_code UNIQUE (platform, version_code),
    CONSTRAINT chk_versions_platform CHECK (platform IN ('ios', 'android')),
    CONSTRAINT chk_versions_policy CHECK (update_policy IN ('force', 'suggest', 'silent')),
    CONSTRAINT chk_versions_status CHECK (status IN ('active', 'inactive'))
);

CREATE INDEX idx_versions_platform ON sdk_versions (platform, version_code DESC);

COMMENT ON TABLE sdk_versions IS 'SDK版本记录。每个平台可有多个版本，按version_code排序取最大。';
COMMENT ON COLUMN sdk_versions.update_policy IS 'force=强制更新(不可跳过), suggest=建议更新(可跳过), silent=静默更新(后台下载)';
```

---

## 4. 物化视图（Phase 2 使用）

### 4.1 每日事件统计

```sql
CREATE MATERIALIZED VIEW mv_daily_event_stats AS
SELECT
    date_trunc('day', server_ts)::DATE AS stat_date,
    event_type,
    app_id,
    payload->>'page'     AS page,
    payload->>'element'  AS element,
    COUNT(*)             AS event_count,
    COUNT(DISTINCT device_id) AS unique_devices
FROM sdk_events
GROUP BY 1, 2, 3, 4, 5;

CREATE UNIQUE INDEX idx_mv_daily ON mv_daily_event_stats (stat_date, event_type, app_id, page, element);
```

### 4.2 每小时趋势

```sql
CREATE MATERIALIZED VIEW mv_hourly_trend AS
SELECT
    date_trunc('hour', server_ts) AS hour,
    event_type,
    COUNT(*)                      AS event_count,
    COUNT(DISTINCT device_id)     AS unique_devices
FROM sdk_events
GROUP BY 1, 2;

CREATE UNIQUE INDEX idx_mv_hourly ON mv_hourly_trend (hour, event_type);
```

### 4.3 刷新函数

```sql
CREATE OR REPLACE FUNCTION refresh_materialized_views()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_daily_event_stats;
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_hourly_trend;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION refresh_materialized_views() IS '刷新所有物化视图。由FastAPI后台定时任务每5分钟调用。';
```

---

## 5. SQLAlchemy ORM 模型定义

Codex 在 `backend/app/models/` 下创建以下三个文件：

### 5.1 models/event.py

```python
"""sdk_events ORM 模型"""
from sqlalchemy import Column, BigInteger, String, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB, INET
from sqlalchemy.sql import func
from app.core.database import Base

class SdkEvent(Base):
    __tablename__ = "sdk_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    event_type = Column(String(50), nullable=False, index=True)
    app_id = Column(String(32), nullable=False)
    device_id = Column(String(64))
    sdk_version = Column(String(20))
    session_id = Column(String(64))
    payload = Column(JSONB, nullable=False)
    client_ts = Column(DateTime(timezone=True))
    server_ts = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ip = Column(INET)
    user_agent = Column(Text)
```

### 5.2 models/config.py

```python
"""sdk_configs ORM 模型"""
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.core.database import Base

class SdkConfig(Base):
    __tablename__ = "sdk_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    version = Column(String(32), unique=True, nullable=False)
    config_data = Column(JSONB, nullable=False)
    status = Column(String(20), nullable=False, default="draft")
    publish_at = Column(DateTime(timezone=True))
    published_by = Column(String(64))
    cos_key = Column(String(256))
    cdn_url = Column(String(512))
    change_log = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

### 5.3 models/version.py

```python
"""sdk_versions ORM 模型"""
from sqlalchemy import Column, Integer, String, BigInteger, DateTime, Text
from sqlalchemy.sql import func
from app.core.database import Base

class SdkVersion(Base):
    __tablename__ = "sdk_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    platform = Column(String(10), nullable=False)
    version_code = Column(Integer, nullable=False)
    version_name = Column(String(20), nullable=False)
    update_policy = Column(String(20), nullable=False, default="suggest")
    download_url = Column(String(512))
    release_notes = Column(Text)
    min_sdk_version = Column(Integer)
    file_size = Column(BigInteger)
    file_hash = Column(String(64))
    status = Column(String(20), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

---

## 6. 分区维护 SQL

### 6.1 自动创建下月分区（每月 25 号执行）

```sql
CREATE OR REPLACE FUNCTION create_next_partition()
RETURNS TEXT AS $$
DECLARE
    next_month DATE := date_trunc('month', NOW())::DATE + INTERVAL '2 months';
    t_name     TEXT;
    t_start    TEXT;
    t_end      TEXT;
BEGIN
    t_name  := 'sdk_events_' || to_char(next_month, 'YYYYMM');
    t_start := to_char(next_month, 'YYYY-MM-DD');
    t_end   := to_char(next_month + INTERVAL '1 month', 'YYYY-MM-DD');

    EXECUTE format('
        CREATE TABLE IF NOT EXISTS %I PARTITION OF sdk_events
        FOR VALUES FROM (%L) TO (%L)',
        t_name, t_start, t_end
    );

    RETURN format('已创建分区: %s (%s ~ %s)', t_name, t_start, t_end);
END;
$$ LANGUAGE plpgsql;
```

### 6.2 清理过期分区（保留 90 天）

```sql
CREATE OR REPLACE FUNCTION cleanup_old_partitions(retention_days INTEGER DEFAULT 90)
RETURNS TEXT AS $$
DECLARE
    cutoff_date DATE := (NOW() - (retention_days || ' days')::INTERVAL)::DATE;
    r RECORD;
    cnt INTEGER := 0;
BEGIN
    FOR r IN
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public'
          AND tablename LIKE 'sdk_events_%'
          AND tablename < 'sdk_events_' || to_char(cutoff_date, 'YYYYMM')
    LOOP
        EXECUTE format('DROP TABLE IF EXISTS %I', r.tablename);
        cnt := cnt + 1;
    END LOOP;
    RETURN format('已清理 %s 个过期分区', cnt);
END;
$$ LANGUAGE plpgsql;
```

---

## 7. 初始数据

```sql
-- 插入一条初始配置模板（让接口有东西可返回）
INSERT INTO sdk_configs (version, config_data, status, change_log)
VALUES (
    '20260630_init',
    '{
        "features": {},
        "rules": [],
        "urls": {
            "api_base": "https://api.example.com",
            "cdn_base": "https://cdn.example.com"
        }
    }'::jsonb,
    'published',
    '初始配置模板（字段结构由SDK同事后续定义）'
) ON CONFLICT (version) DO NOTHING;
```

---

## 8. 环境变量（.env 文件）

```env
# backend/.env
DATABASE_URL=postgresql+asyncpg://admin:${DB_PASSWORD}@localhost:5432/sdk_platform
DEBUG=false
LOG_LEVEL=INFO
DB_PASSWORD=your_password_here

# 腾讯云 COS（Phase 2 配置）
COS_SECRET_ID=your_secret_id
COS_SECRET_KEY=your_secret_key
COS_REGION=ap-guangzhou
COS_BUCKET=sdk-config-bucket-1234567890

# CDN
CDN_BASE_URL=https://cdn.example.com
```

---

> 🍔 数据库文档完。下一份 → `04-IMPLEMENTATION-PLAN.md` 分期实施计划
