import pytest
from pathlib import Path

from scripts.migrate_package_encrypted_configs import prepare_legacy_config


def test_migration_accepts_three_way_config():
    config = {"mainConfig": {}, "newTouchConfig": {}, "newTextRuleConfig": {}}
    assert prepare_legacy_config(config) is config


def test_migration_rejects_legacy_single_payload_before_schema_switch():
    with pytest.raises(ValueError, match="mainConfig"):
        prepare_legacy_config({"features": {}})


def test_explicit_legacy_conversion_wraps_whole_payload_as_main():
    legacy = {"features": {}, "rules": [], "urls": {}}
    assert prepare_legacy_config(legacy, legacy_single_as_main=True) == {
        "mainConfig": legacy,
        "newTouchConfig": {},
        "newTextRuleConfig": {},
    }


def test_expand_migration_makes_retained_plaintext_column_nullable():
    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "migrate_package_encrypted_configs.py"
    ).read_text(encoding="utf-8")
    assert "ALTER TABLE sdk_configs ALTER COLUMN config_data DROP NOT NULL" in script
