from __future__ import annotations

import base64
import json
import os
import re
from typing import Any, Mapping

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

ALGORITHM = "AES-256-GCM"
KEY_ID = "v1"
_SALT = b"sdk-config-encryption-v1"
_INFO = b"sdk-config/aes-256-gcm"
_PACKAGE_PATTERN = re.compile(r"^[a-z0-9_][a-z0-9_.-]{0,254}$")
CONFIG_TYPES = frozenset({"full", "main", "new_touch", "new_text_rule"})


class ConfigDecryptionError(ValueError):
    """Raised when an encrypted configuration cannot be authenticated."""


def normalize_package_name(value: str) -> str:
    normalized = value.strip().lower()
    if not _PACKAGE_PATTERN.fullmatch(normalized):
        raise ValueError("包名格式无效")
    return normalized


def _derive_key(token: str) -> bytes:
    if not token or len(token) < 24:
        raise ValueError("SDK_CONFIG_TOKEN 长度不足，无法安全派生配置密钥")
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        info=_INFO,
    ).derive(token.encode("utf-8"))


def _aad(package_name: str, version: str, config_type: str) -> bytes:
    return (
        f"package_name={normalize_package_name(package_name)}"
        f"&version={version}&config_type={config_type}"
    ).encode("utf-8")


def encrypt_payload(
    payload: Any,
    package_name: str,
    version: str,
    config_type: str,
    token: str,
) -> dict[str, str]:
    if config_type not in CONFIG_TYPES:
        raise ValueError("配置类型无效")
    package_name = normalize_package_name(package_name)
    nonce = os.urandom(12)
    plaintext = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ciphertext = AESGCM(_derive_key(token)).encrypt(
        nonce, plaintext, _aad(package_name, version, config_type)
    )
    return {
        "version": version,
        "package_name": package_name,
        "config_type": config_type,
        "algorithm": ALGORITHM,
        "key_id": KEY_ID,
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }


def decrypt_payload(envelope: Mapping[str, Any], token: str) -> Any:
    try:
        if envelope["algorithm"] != ALGORITHM or envelope["key_id"] != KEY_ID:
            raise ConfigDecryptionError("不支持的配置加密协议")
        package_name = normalize_package_name(str(envelope["package_name"]))
        version = str(envelope["version"])
        config_type = str(envelope["config_type"])
        if config_type not in CONFIG_TYPES:
            raise ConfigDecryptionError("配置类型无效")
        nonce = base64.b64decode(str(envelope["nonce"]), validate=True)
        ciphertext = base64.b64decode(str(envelope["ciphertext"]), validate=True)
        if len(nonce) != 12:
            raise ConfigDecryptionError("nonce 长度无效")
        plaintext = AESGCM(_derive_key(token)).decrypt(
            nonce, ciphertext, _aad(package_name, version, config_type)
        )
        return json.loads(plaintext.decode("utf-8"))
    except ConfigDecryptionError:
        raise
    except (InvalidTag, KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigDecryptionError("配置解密或完整性校验失败") from exc
