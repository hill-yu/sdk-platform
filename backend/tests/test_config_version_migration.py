from datetime import datetime, timezone

import pytest

from app.services.config_crypto import ConfigDecryptionError, decrypt_payload, encrypt_payload
from scripts.migrate_config_versions import build_version_mapping, local_delivery_url, prepare_migration


TOKEN = "sdk-config-test-token-1234567890"
PLAIN = {"mainConfig": {"ok": True}, "newTouchConfig": {}, "newTextRuleConfig": {}}


def _row(
    record_id: int,
    package_name: str,
    version: str,
    published_at: datetime,
    *,
    envelope: dict | None = None,
) -> dict:
    return {
        "id": record_id,
        "package_name": package_name,
        "version": version,
        "status": "published" if record_id == 2 else "archived",
        "publish_at": published_at,
        "created_at": published_at,
        "encrypted_config": envelope
        or encrypt_payload(PLAIN, package_name, version, "full", TOKEN),
    }


def test_build_mapping_is_stable_and_independent_per_package():
    first = datetime(2026, 1, 1, tzinfo=timezone.utc)
    second = datetime(2026, 1, 2, tzinfo=timezone.utc)
    rows = [
        _row(2, "com.a", "old-b", second),
        _row(1, "com.a", "old-a", first),
        _row(3, "com.b", "legacy", first),
    ]

    assert build_version_mapping(rows) == {1: "1.0.0", 2: "1.0.1", 3: "1.0.0"}


def test_prepare_migration_reencrypts_with_new_version_aad():
    row = _row(1, "com.a", "legacy", datetime(2026, 1, 1, tzinfo=timezone.utc))

    prepared = prepare_migration([row], TOKEN)

    assert prepared[0]["version"] == "1.0.0"
    assert prepared[0]["envelope"]["version"] == "1.0.0"
    assert decrypt_payload(prepared[0]["envelope"], TOKEN) == PLAIN


def test_prepare_migration_is_idempotent_for_migrated_rows():
    row = _row(1, "com.a", "1.0.0", datetime(2026, 1, 1, tzinfo=timezone.utc))

    prepared = prepare_migration([row], TOKEN)

    assert prepared[0]["changed"] is False
    assert prepared[0]["envelope"] == row["encrypted_config"]


def test_prepare_migration_validates_every_ciphertext_before_writes():
    first = _row(1, "com.a", "old-a", datetime(2026, 1, 1, tzinfo=timezone.utc))
    broken = _row(2, "com.a", "old-b", datetime(2026, 1, 2, tzinfo=timezone.utc))
    broken["encrypted_config"] = {**broken["encrypted_config"], "ciphertext": "AAAA"}

    with pytest.raises(ConfigDecryptionError):
        prepare_migration([first, broken], TOKEN)


def test_local_delivery_url_uses_migrated_package_and_version():
    assert local_delivery_url("https://sdk.example.test/", "com.a", "1.0.1") == (
        "https://sdk.example.test/api/v1/config/packages/com.a/versions/1.0.1/main"
    )
