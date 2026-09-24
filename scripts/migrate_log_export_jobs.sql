CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS sdk_log_export_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    package_names JSONB NOT NULL,
    device_id VARCHAR(64),
    log_level VARCHAR(10),
    date_from DATE,
    hour_from SMALLINT,
    date_to DATE,
    hour_to SMALLINT,
    file_path TEXT,
    row_count BIGINT NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    CONSTRAINT chk_log_export_jobs_status CHECK (status IN ('pending', 'running', 'success', 'failed')),
    CONSTRAINT chk_log_export_jobs_hour_pair CHECK (
        (hour_from IS NULL AND hour_to IS NULL) OR
        (hour_from IS NOT NULL AND hour_to IS NOT NULL)
    ),
    CONSTRAINT chk_log_export_jobs_hour_bounds CHECK (
        (hour_from IS NULL OR hour_from BETWEEN 0 AND 23) AND
        (hour_to IS NULL OR hour_to BETWEEN 0 AND 23)
    )
);

CREATE INDEX IF NOT EXISTS idx_log_export_jobs_status_created
    ON sdk_log_export_jobs (status, created_at);

ALTER TABLE sdk_log_export_jobs
    ADD COLUMN IF NOT EXISTS sdk_version VARCHAR(20);

ALTER TABLE sdk_log_export_jobs
    ADD COLUMN IF NOT EXISTS hour_from SMALLINT;

ALTER TABLE sdk_log_export_jobs
    ADD COLUMN IF NOT EXISTS hour_to SMALLINT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_log_export_jobs_hour_pair'
          AND conrelid = 'sdk_log_export_jobs'::regclass
    ) THEN
        ALTER TABLE sdk_log_export_jobs
            ADD CONSTRAINT chk_log_export_jobs_hour_pair CHECK (
                (hour_from IS NULL AND hour_to IS NULL) OR
                (hour_from IS NOT NULL AND hour_to IS NOT NULL)
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_log_export_jobs_hour_bounds'
          AND conrelid = 'sdk_log_export_jobs'::regclass
    ) THEN
        ALTER TABLE sdk_log_export_jobs
            ADD CONSTRAINT chk_log_export_jobs_hour_bounds CHECK (
                (hour_from IS NULL OR hour_from BETWEEN 0 AND 23) AND
                (hour_to IS NULL OR hour_to BETWEEN 0 AND 23)
            );
    END IF;
END $$;
