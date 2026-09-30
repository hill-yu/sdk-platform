-- Structured H1 declarations, click attempts, and explicit parse-job progress.
-- This migration is additive and safe to run repeatedly.

ALTER TABLE IF EXISTS sdk_log_reparse_jobs
    ADD COLUMN IF NOT EXISTS snapshot_end TIMESTAMPTZ;
UPDATE sdk_log_reparse_jobs
SET snapshot_end = range_end
WHERE snapshot_end IS NULL;
ALTER TABLE IF EXISTS sdk_log_reparse_jobs
    ALTER COLUMN snapshot_end SET NOT NULL;

ALTER TABLE IF EXISTS sdk_log_reparse_jobs
    ADD COLUMN IF NOT EXISTS total_count BIGINT NOT NULL DEFAULT 0;
ALTER TABLE IF EXISTS sdk_log_reparse_jobs
    ADD COLUMN IF NOT EXISTS h1_count BIGINT NOT NULL DEFAULT 0;
ALTER TABLE IF EXISTS sdk_log_reparse_jobs
    ADD COLUMN IF NOT EXISTS failed_h1_count BIGINT NOT NULL DEFAULT 0;
ALTER TABLE IF EXISTS sdk_log_reparse_jobs
    ADD COLUMN IF NOT EXISTS no_h1_count BIGINT NOT NULL DEFAULT 0;
ALTER TABLE IF EXISTS sdk_log_reparse_jobs
    ADD COLUMN IF NOT EXISTS batch_size INTEGER NOT NULL DEFAULT 200;
ALTER TABLE IF EXISTS sdk_log_reparse_jobs
    ADD COLUMN IF NOT EXISTS concurrency INTEGER NOT NULL DEFAULT 3;
ALTER TABLE IF EXISTS sdk_log_reparse_jobs
    ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
ALTER TABLE IF EXISTS sdk_log_reparse_jobs
    ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ;
ALTER TABLE IF EXISTS sdk_log_reparse_jobs
    ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMPTZ;
ALTER TABLE IF EXISTS sdk_log_reparse_jobs
    ADD COLUMN IF NOT EXISTS cancel_requested_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS sdk_log_h1_declarations (
    event_id BIGINT NOT NULL,
    event_server_ts TIMESTAMPTZ NOT NULL,
    record_index INTEGER NOT NULL,
    package_name VARCHAR(255) NOT NULL,
    device_id VARCHAR(64),
    sdk_version VARCHAR(20),
    config_id INTEGER,
    "window" VARCHAR(32),
    declared_click_count INTEGER,
    interstitial_presentation_count INTEGER NOT NULL DEFAULT 0,
    interstitial_click_count INTEGER NOT NULL DEFAULT 0,
    interstitial_close_count INTEGER NOT NULL DEFAULT 0,
    flow_duration_ms BIGINT,
    final_reason VARCHAR(128),
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    parse_error VARCHAR(512),
    decoder_version VARCHAR(32) NOT NULL,
    parsed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decoded_payload JSONB,
    CONSTRAINT pk_sdk_log_h1_declarations PRIMARY KEY (event_id, event_server_ts, record_index)
);

CREATE TABLE IF NOT EXISTS sdk_log_click_attempts (
    event_id BIGINT NOT NULL,
    event_server_ts TIMESTAMPTZ NOT NULL,
    record_index INTEGER NOT NULL,
    attempt_index INTEGER NOT NULL,
    package_name VARCHAR(255) NOT NULL,
    config_id INTEGER,
    target_kind VARCHAR(64),
    did_click BOOLEAN,
    navigation_code INTEGER,
    reason VARCHAR(128),
    error_detail TEXT,
    navigation_result VARCHAR(128),
    failure_category VARCHAR(128),
    click_timestamp TIMESTAMPTZ,
    page_context VARCHAR(32),
    decoder_version VARCHAR(32) NOT NULL,
    CONSTRAINT pk_sdk_log_click_attempts PRIMARY KEY (
        event_id, event_server_ts, record_index, attempt_index
    )
);

CREATE TABLE IF NOT EXISTS sdk_log_h1_declaration_stage (
    job_id BIGINT NOT NULL,
    event_id BIGINT NOT NULL,
    event_server_ts TIMESTAMPTZ NOT NULL,
    record_index INTEGER NOT NULL,
    package_name VARCHAR(255) NOT NULL,
    device_id VARCHAR(64),
    sdk_version VARCHAR(20),
    config_id INTEGER,
    "window" VARCHAR(32),
    declared_click_count INTEGER,
    interstitial_presentation_count INTEGER NOT NULL DEFAULT 0,
    interstitial_click_count INTEGER NOT NULL DEFAULT 0,
    interstitial_close_count INTEGER NOT NULL DEFAULT 0,
    flow_duration_ms BIGINT,
    final_reason VARCHAR(128),
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    parse_error VARCHAR(512),
    decoder_version VARCHAR(32) NOT NULL,
    parsed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decoded_payload JSONB,
    CONSTRAINT pk_sdk_log_h1_declaration_stage PRIMARY KEY (
        job_id, event_id, event_server_ts, record_index
    )
);

CREATE TABLE IF NOT EXISTS sdk_log_click_attempt_stage (
    job_id BIGINT NOT NULL,
    event_id BIGINT NOT NULL,
    event_server_ts TIMESTAMPTZ NOT NULL,
    record_index INTEGER NOT NULL,
    attempt_index INTEGER NOT NULL,
    package_name VARCHAR(255) NOT NULL,
    config_id INTEGER,
    target_kind VARCHAR(64),
    did_click BOOLEAN,
    navigation_code INTEGER,
    reason VARCHAR(128),
    error_detail TEXT,
    navigation_result VARCHAR(128),
    failure_category VARCHAR(128),
    click_timestamp TIMESTAMPTZ,
    page_context VARCHAR(32),
    decoder_version VARCHAR(32) NOT NULL,
    CONSTRAINT pk_sdk_log_click_attempt_stage PRIMARY KEY (
        job_id, event_id, event_server_ts, record_index, attempt_index
    )
);

CREATE INDEX IF NOT EXISTS idx_log_h1_package_ts_config
    ON sdk_log_h1_declarations (package_name, event_server_ts, config_id);
CREATE INDEX IF NOT EXISTS idx_log_click_package_ts_config_target
    ON sdk_log_click_attempts (package_name, event_server_ts, config_id, target_kind);
CREATE INDEX IF NOT EXISTS idx_log_h1_stage_job
    ON sdk_log_h1_declaration_stage (job_id);
CREATE INDEX IF NOT EXISTS idx_log_click_stage_job
    ON sdk_log_click_attempt_stage (job_id);
