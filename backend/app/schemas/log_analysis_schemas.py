from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.config_crypto import normalize_package_name


class PackageProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alias: str | None = Field(default=None, max_length=255)
    company: str | None = Field(default=None, max_length=255)
    account: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def require_one_field(self):
        if not self.model_fields_set:
            raise ValueError("至少提交一个包资料字段")
        return self


class PackageProfileResponse(BaseModel):
    package_name: str
    alias: str
    company: str
    account: str


class LogAnalysisColumnsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: list[str] = Field(min_length=1, max_length=16)

    @field_validator("columns")
    @classmethod
    def validate_columns(cls, value: list[str]) -> list[str]:
        from app.services.log_analysis_service import validate_column_selection

        return validate_column_selection(value)


class LogAnalysisColumnsResponse(BaseModel):
    available_columns: list[str]
    default_columns: list[str]
    columns: list[str]


class LogReparseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date_from: date | None = None
    date_to: date | None = None
    package_name: str | None = Field(default=None, max_length=255)
    status: Literal["pending", "success", "unsupported", "failed"] | None = None
    decoder_version_before: str | None = Field(default=None, max_length=32)

    @field_validator("package_name")
    @classmethod
    def normalize_package(cls, value: str | None) -> str | None:
        return normalize_package_name(value) if value is not None else None

    @model_validator(mode="after")
    def validate_scope(self):
        if (self.date_from is None) != (self.date_to is None):
            raise ValueError("date_from 和 date_to 必须成对提供")
        if self.date_from is not None and self.date_from > self.date_to:
            raise ValueError("date_from 不能晚于 date_to")
        if not any(
            value is not None
            for value in (
                self.date_from,
                self.date_to,
                self.package_name,
                self.status,
                self.decoder_version_before,
            )
        ):
            raise ValueError("reparse 必须指定范围或筛选条件")
        if self.decoder_version_before is not None:
            from app.services.log_analysis_service import parse_decoder_version

            parse_decoder_version(self.decoder_version_before)
        return self
