-- ============================================================
-- SDK 数据中台 + 配置管理系统 — 数据库初始化脚本
-- PostgreSQL 15+
-- 用法: psql -U admin -d sdk_platform -f init_db.sql
-- ============================================================

-- ============================================================
-- 1. 扩展
-- ============================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- 2. SDK 原始事件表（按月分区）
-- ============================================================
CREATE TABLE IF NOT EXISTS sdk_events (
    id              BIGSERIAL,
    event_type      VARCHAR(50)   NOT NULL,
    app_id          VARCHAR(32)   NOT NULL,
    device_id       VARCHAR(64),
    sdk_version     VARCHAR(20),
    session_id      VARCHAR(64),
    payload         JSONB         NOT NULL,
    client_ts       TIMESTAMPTZ,
    server_ts       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    ip              INET,
    user_agent      TEXT,

    CONSTRAINT pk_sdk_events PRIMARY KEY (id, server_ts)
) PARTITION BY RANGE (server_ts);

-- 创建当月 + 未来2个月分区
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

-- 索引
CREATE INDEX IF NOT EXISTS idx_events_type_ts ON sdk_events (event_type, server_ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_device ON sdk_events (device_id, server_ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_app ON sdk_events (app_id, server_ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_session ON sdk_events (session_id, server_ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_payload ON sdk_events USING GIN (payload jsonb_path_ops);
CREATE INDEX IF NOT EXISTS idx_events_client_ts ON sdk_events (client_ts DESC);

COMMENT ON TABLE sdk_events IS 'SDK原始事件表（按月分区）';
COMMENT ON COLUMN sdk_events.payload IS 'JSONB灵活存储事件数据';

-- ============================================================
-- 3. 配置表版本记录
-- ============================================================
CREATE TABLE IF NOT EXISTS sdk_configs (
    id              SERIAL PRIMARY KEY,
    version         VARCHAR(32)   NOT NULL,
    config_data     JSONB         NOT NULL,
    status          VARCHAR(20)   NOT NULL DEFAULT 'draft',
    publish_at      TIMESTAMPTZ,
    published_by    VARCHAR(64),
    cos_key         VARCHAR(256),
    cdn_url         VARCHAR(512),
    change_log      TEXT,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_configs_version UNIQUE (version),
    CONSTRAINT chk_configs_status CHECK (status IN ('draft', 'published', 'archived'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_configs_one_published ON sdk_configs (status) WHERE status = 'published';
CREATE INDEX IF NOT EXISTS idx_configs_status ON sdk_configs (status, created_at DESC);

COMMENT ON TABLE sdk_configs IS '配置表版本记录';

-- ============================================================
-- 4. SDK 版本管理
-- ============================================================
CREATE TABLE IF NOT EXISTS sdk_versions (
    id              SERIAL PRIMARY KEY,
    platform        VARCHAR(10)   NOT NULL,
    version_code    INTEGER       NOT NULL,
    version_name    VARCHAR(20)   NOT NULL,
    update_policy   VARCHAR(20)   NOT NULL DEFAULT 'suggest',
    download_url    VARCHAR(512),
    release_notes   TEXT,
    min_sdk_version INTEGER,
    file_size       BIGINT,
    file_hash       VARCHAR(64),
    status          VARCHAR(20)   NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_versions_platform_code UNIQUE (platform, version_code),
    CONSTRAINT chk_versions_platform CHECK (platform IN ('ios', 'android')),
    CONSTRAINT chk_versions_policy CHECK (update_policy IN ('force', 'suggest', 'silent')),
    CONSTRAINT chk_versions_status CHECK (status IN ('active', 'inactive'))
);

CREATE INDEX IF NOT EXISTS idx_versions_platform ON sdk_versions (platform, version_code DESC);

COMMENT ON TABLE sdk_versions IS 'SDK版本记录';

-- ============================================================
-- 5. 分析物化视图
-- ============================================================
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_daily_event_stats AS
SELECT
    date_trunc('day', server_ts)::DATE AS stat_date,
    event_type,
    app_id,
    payload->>'page'     AS page,
    payload->>'element' AS element,
    COUNT(*)            AS event_count,
    COUNT(DISTINCT device_id) AS unique_devices
FROM sdk_events
GROUP BY 1, 2, 3, 4, 5;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_daily ON mv_daily_event_stats (stat_date, event_type, app_id, page, element);

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_hourly_trend AS
SELECT
    date_trunc('hour', server_ts) AS hour,
    event_type,
    COUNT(*)                      AS event_count,
    COUNT(DISTINCT device_id)     AS unique_devices
FROM sdk_events
GROUP BY 1, 2;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_hourly ON mv_hourly_trend (hour, event_type);

-- ============================================================
-- 6. 刷新物化视图函数
-- ============================================================
CREATE OR REPLACE FUNCTION refresh_materialized_views()
RETURNS void AS $$
BEGIN
    IF pg_try_advisory_xact_lock(12345) THEN
        REFRESH MATERIALIZED VIEW CONCURRENTLY mv_daily_event_stats;
        REFRESH MATERIALIZED VIEW CONCURRENTLY mv_hourly_trend;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- 7. 分区维护函数
-- ============================================================
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
    RETURN format('已创建分区: %s', t_name);
END;
$$ LANGUAGE plpgsql;

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

-- ============================================================
-- 8. 初始数据
-- ============================================================
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

-- ============================================================
-- 完成
-- ============================================================
DO $$
BEGIN
    RAISE NOTICE '========================================';
    RAISE NOTICE '数据库初始化完成！';
    RAISE NOTICE '表: sdk_events, sdk_configs, sdk_versions';
    RAISE NOTICE '视图: mv_daily_event_stats, mv_hourly_trend';
    RAISE NOTICE '========================================';
END $$;
