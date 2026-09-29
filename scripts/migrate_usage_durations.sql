BEGIN;

CREATE TABLE IF NOT EXISTS sdk_usage_durations (
    id              BIGSERIAL PRIMARY KEY,
    package_name    VARCHAR(255) NOT NULL,
    device_id       VARCHAR(64)  NOT NULL,
    device_model    VARCHAR(100) NOT NULL,
    os              VARCHAR(50)  NOT NULL,
    app_version     VARCHAR(50)  NOT NULL,
    sdk_version     VARCHAR(20)  NOT NULL,
    duration_s      INTEGER      NOT NULL,
    server_ts       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    ip              INET,
    user_agent      TEXT,
    CONSTRAINT chk_usage_durations_duration_s
        CHECK (duration_s BETWEEN 1 AND 3600)
);

CREATE INDEX IF NOT EXISTS idx_usage_durations_server_ts
    ON sdk_usage_durations (server_ts DESC);
CREATE INDEX IF NOT EXISTS idx_usage_durations_package_ts
    ON sdk_usage_durations (package_name, server_ts DESC);
CREATE INDEX IF NOT EXISTS idx_usage_durations_package_device_ts
    ON sdk_usage_durations (package_name, device_id, server_ts DESC);

COMMIT;
