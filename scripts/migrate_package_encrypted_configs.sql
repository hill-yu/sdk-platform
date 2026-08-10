BEGIN;

ALTER TABLE sdk_configs ADD COLUMN IF NOT EXISTS package_name VARCHAR(255);
ALTER TABLE sdk_configs ADD COLUMN IF NOT EXISTS encrypted_config JSONB;
ALTER TABLE sdk_configs ADD COLUMN IF NOT EXISTS encryption_key_id VARCHAR(32) DEFAULT 'v1';

-- 此处暂停，由 migrate_package_encrypted_configs.py 显式指定默认包名并完成加密回填。
-- Python 脚本验证所有记录后执行下列约束切换。

COMMIT;
