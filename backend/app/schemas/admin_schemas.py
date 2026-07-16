from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ConfigUpsertRequest(BaseModel):
    config_data: dict[str, Any]
    change_log: str = ""

    @field_validator("config_data")
    @classmethod
    def validate_size(cls, v: dict) -> dict:
        json_bytes = json.dumps(v, ensure_ascii=False).encode("utf-8")
        if len(json_bytes) > 500_000:
            raise ValueError(f"config_data JSON 大小超过 500KB 限制（当前 {len(json_bytes)} 字节）")
        return v


class VersionCreateRequest(BaseModel):
    platform: Literal["ios", "android"]
    version_code: int
    version_name: str
    update_policy: Literal["force", "suggest", "silent"] = "suggest"
    download_url: str | None = None
    release_notes: str | None = None
    min_sdk_version: int | None = None
    file_size: int | None = None
    file_hash: str | None = None
    status: Literal["active", "inactive"] = "active"


class VersionUpdateRequest(BaseModel):
    version_name: str | None = None
    update_policy: Literal["force", "suggest", "silent"] | None = None
    download_url: str | None = None
    release_notes: str | None = None
    min_sdk_version: int | None = None
    file_size: int | None = None
    file_hash: str | None = None
    status: Literal["active", "inactive"] | None = None


class PaginatedEventsResponse(BaseModel):
    total: int
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    items: list[dict[str, Any]]
