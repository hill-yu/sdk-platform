import pytest

from scripts.migrate_package_encrypted_configs import validate_legacy_config


def test_migration_accepts_three_way_config():
    config = {"mainConfig": {}, "newTouchConfig": {}, "newTextRuleConfig": {}}
    assert validate_legacy_config(config) is config


def test_migration_rejects_legacy_single_payload_before_schema_switch():
    with pytest.raises(ValueError, match="mainConfig"):
        validate_legacy_config({"features": {}})
