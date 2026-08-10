import copy
import json
from pathlib import Path

import pytest

from app.services.config_crypto import (
    ConfigDecryptionError,
    decrypt_payload,
    encrypt_payload,
    normalize_package_name,
)

TOKEN = "sdk-config-test-token-1234567890"
CONFIG = {"enabled": True, "rules": ["one", "two"]}


def test_encrypt_round_trip_uses_unique_nonce():
    first = encrypt_payload(CONFIG, "com.Example.App", "1.0.11", "main", TOKEN)
    second = encrypt_payload(CONFIG, "com.example.app", "1.0.11", "main", TOKEN)
    assert first["nonce"] != second["nonce"]
    assert first["package_name"] == "com.example.app"
    assert decrypt_payload(first, TOKEN) == CONFIG


@pytest.mark.parametrize("field,value", [
    ("package_name", "com.other.app"),
    ("version", "1.0.12"),
    ("config_type", "new_touch"),
    ("nonce", "AAAAAAAAAAAAAAAA"),
])
def test_tampered_envelope_is_rejected(field, value):
    envelope = encrypt_payload(CONFIG, "com.example.app", "1.0.11", "main", TOKEN)
    tampered = copy.deepcopy(envelope)
    tampered[field] = value
    with pytest.raises(ConfigDecryptionError):
        decrypt_payload(tampered, TOKEN)


def test_wrong_token_is_rejected():
    envelope = encrypt_payload(CONFIG, "com.example.app", "1.0.11", "main", TOKEN)
    with pytest.raises(ConfigDecryptionError):
        decrypt_payload(envelope, "different-token-with-enough-entropy")


def test_public_cross_platform_vector_decrypts():
    vector_path = Path(__file__).resolve().parents[2] / "docs" / "SDK-CONFIG-CRYPTO-TEST-VECTOR.json"
    vector = json.loads(vector_path.read_text(encoding="utf-8"))
    assert decrypt_payload(vector["envelope"], vector["token"]) == vector["expected_json"]


@pytest.mark.parametrize("value", ["", "a/b", "*", "a b", ".leading"])
def test_invalid_package_name_is_rejected(value):
    with pytest.raises(ValueError):
        normalize_package_name(value)
