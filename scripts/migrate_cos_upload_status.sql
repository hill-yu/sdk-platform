-- 迁移: 添加 cos_upload_status 列
-- 适用于已有 sdk_configs 表的数据库升级

ALTER TABLE sdk_configs
ADD COLUMN IF NOT EXISTS cos_upload_status VARCHAR(20);

UPDATE sdk_configs
SET cos_upload_status = CASE
    WHEN status = 'published' THEN 'success'
    ELSE 'pending'
END
WHERE cos_upload_status IS NULL;

ALTER TABLE sdk_configs
ALTER COLUMN cos_upload_status SET DEFAULT 'pending',
ALTER COLUMN cos_upload_status SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_configs_cos_upload_status'
    ) THEN
        ALTER TABLE sdk_configs
        ADD CONSTRAINT chk_configs_cos_upload_status
        CHECK (cos_upload_status IN ('pending', 'success', 'failed'));
    END IF;
END $$;
