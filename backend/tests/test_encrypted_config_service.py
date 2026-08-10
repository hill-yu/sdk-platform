from datetime import datetime, timezone

import pytest

from app.services import config_service
from app.services.config_crypto import decrypt_payload


class Db:
    def __init__(self):
        self.added = None
    def add(self, value): self.added = value
    async def flush(self):
        if self.added and self.added.id is None:
            self.added.id = 1


@pytest.mark.anyio
async def test_create_config_persists_only_encrypted_payload(monkeypatch):
    monkeypatch.setenv("SDK_CONFIG_TOKEN", "sdk-config-test-token-1234567890")
    from app.core.config import get_settings
    get_settings.cache_clear()
    db = Db()
    source = {"mainConfig": {"secret": "value"}, "newTouchConfig": {}, "newTextRuleConfig": {}}
    result = await config_service.create_config(db, "COM.EXAMPLE.APP", source, "init")
    assert result["package_name"] == "com.example.app"
    assert not hasattr(db.added, "config_data")
    assert "secret" not in str(db.added.encrypted_config)
    assert decrypt_payload(db.added.encrypted_config, "sdk-config-test-token-1234567890") == source
    get_settings.cache_clear()


def test_delivery_paths_are_isolated_by_package_and_version(monkeypatch):
    monkeypatch.setenv("CONFIG_DELIVERY_MODE", "cos")
    monkeypatch.setenv("CDN_BASE_URL", "https://cdn.example.test")
    from app.core.config import get_settings
    get_settings.cache_clear()
    first = config_service._delivery_url("com.a.app", "v1", "main")
    second = config_service._delivery_url("com.b.app", "v1", "main")
    assert first != second
    assert "/com.a.app/v1/main.json" in first
    assert "/com.b.app/v1/main.json" in second
    get_settings.cache_clear()
