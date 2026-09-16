CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS sdk_log_export_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    package_names JSONB NOT NULL,
    device_id VARCHAR(64),
    log_level VARCHAR(10),
    date_from DATE,
    date_to DATE,
    file_path TEXT,
    row_count BIGINT NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    CONSTRAINT chk_log_export_jobs_status CHECK (status IN ('pending', 'running', 'success', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_log_export_jobs_status_created
    ON sdk_log_export_jobs (status, created_at);
