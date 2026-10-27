-- Additive, repeatable migration for the package source directory.
BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
SELECT pg_advisory_xact_lock(hashtextextended('sdk_package_catalog_migration', 0));

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm')
       AND NOT has_database_privilege(current_user, current_database(), 'CREATE') THEN
        RAISE EXCEPTION 'current user lacks CREATE privilege required to install pg_trgm';
    END IF;
    IF NOT has_schema_privilege(current_user, 'public', 'CREATE') THEN
        RAISE EXCEPTION 'current user lacks CREATE privilege on schema public';
    END IF;
END $$;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS sdk_package_catalog (
    package_name VARCHAR(255) PRIMARY KEY,
    has_log BOOLEAN NOT NULL DEFAULT FALSE,
    has_usage BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_package_catalog_name_trgm
    ON sdk_package_catalog USING GIN (package_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_package_catalog_log_name
    ON sdk_package_catalog (package_name) WHERE has_log;
CREATE INDEX IF NOT EXISTS idx_package_catalog_usage_name
    ON sdk_package_catalog (package_name) WHERE has_usage;

COMMENT ON TABLE sdk_package_catalog IS '包名来源目录，避免管理端下拉扫描事实表';
COMMENT ON COLUMN sdk_package_catalog.has_log IS '是否存在 sdk_events.event_type=log 的原始日志';
COMMENT ON COLUMN sdk_package_catalog.has_usage IS '是否存在 sdk_usage_durations 使用时长';

COMMIT;
